"""SoapVoice Process Supervisor for Windows Agent (Phase 32 Plan 32-12, B4).

(D-32-05, D-32-21)
Rules:
1. ElcAgent manages and monitors the SoapVoice child process.
2. If SoapVoice terminates unexpectedly, restart with exponential backoff.
3. If restart count exceeds max_restarts, transition to "gave_up" state.
4. If SoapVoice is already running externally (health_fn returns True), do not start a duplicate child.
5. Child process runs with CREATE_NO_WINDOW on Windows to prevent console popup.
6. When ElcAgent exits, terminate child process; on Windows, assign to a Job Object
   with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE so child terminates even if parent crashes.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any, Callable, List, Optional, Union

logger = logging.getLogger("windows_agent.supervisor")

CREATE_NO_WINDOW = 0x08000000


def default_soapvoice_exe_path(settings: Any = None) -> Path:
    """Return default path to SoapVoice.exe according to D-32-21 installer layout."""
    if settings is not None and getattr(settings, "soapvoice_exe_path", None):
        return Path(settings.soapvoice_exe_path)
    # Default layout: {app}/SoapVoice/SoapVoice.exe
    return Path(sys.executable).parent / "SoapVoice" / "SoapVoice.exe"


def assign_kill_on_close_job(proc: Any) -> bool:
    """Assign process to a Windows Job Object with KILL_ON_JOB_CLOSE.

    Safe on non-Windows platforms (returns False without exception).
    """
    if sys.platform != "win32":
        return False

    try:
        import ctypes
        from ctypes import wintypes

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryLimit", ctypes.c_size_t),
                ("PeakJobMemoryLimit", ctypes.c_size_t),
            ]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JobObjectExtendedLimitInformation = 9

        kernel32 = ctypes.windll.kernel32
        h_job = kernel32.CreateJobObjectW(None, None)
        if not h_job:
            logger.warning("CreateJobObjectW failed")
            return False

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        res = kernel32.SetInformationJobObject(
            h_job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not res:
            logger.warning("SetInformationJobObject failed")
            kernel32.CloseHandle(h_job)
            return False

        proc_handle = getattr(proc, "_handle", None)
        if proc_handle is None and hasattr(proc, "pid"):
            PROCESS_SET_QUOTA = 0x0100
            PROCESS_TERMINATE = 0x0001
            proc_handle = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, proc.pid)

        if not proc_handle:
            logger.warning("Cannot obtain process handle for Job Object assignment")
            kernel32.CloseHandle(h_job)
            return False

        assign_res = kernel32.AssignProcessToJobObject(h_job, proc_handle)
        if not assign_res:
            logger.warning("AssignProcessToJobObject failed")
            kernel32.CloseHandle(h_job)
            return False

        # Store job handle on process to keep it alive
        proc._job_handle = h_job
        logger.info("Successfully assigned SoapVoice pid=%s to Job Object", getattr(proc, "pid", "unknown"))
        return True

    except Exception as exc:
        logger.warning("assign_kill_on_close_job encountered error: %s", exc)
        return False


class SoapVoiceSupervisor:
    """Supervises SoapVoice child process with backoff restarts and health detection."""

    def __init__(
        self,
        exe_path: Union[str, Path],
        popen_factory: Optional[Callable[..., Any]] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
        sleep: Optional[Callable[[float], None]] = None,
        exists_fn: Optional[Callable[[Union[str, Path]], bool]] = None,
        exists: Optional[Callable[[Union[str, Path]], bool]] = None,
        clock_fn: Optional[Callable[[], float]] = None,
        health_fn: Optional[Callable[[], bool]] = None,
        on_state: Optional[Callable[[str], None]] = None,
        max_restarts: int = 5,
        backoff_base: float = 1.0,
        backoff_max: float = 60.0,
        stable_seconds: float = 300.0,
        log_file: Optional[Union[str, Path]] = None,
    ):
        self.exe_path = Path(exe_path)
        self.popen_factory = popen_factory or subprocess.Popen
        self.sleep_fn = sleep_fn or sleep or time.sleep
        self.exists_fn = exists_fn or exists or os.path.exists
        self.clock_fn = clock_fn or time.time
        self.health_fn = health_fn
        self.on_state = on_state
        self.max_restarts = max_restarts
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.stable_seconds = stable_seconds
        self.log_file = Path(log_file) if log_file else None

        self.proc: Optional[Any] = None
        self.restart_count: int = 0
        self.started_at: float = 0.0
        self.state: str = "init"  # "missing", "external", "running", "restarting", "gave_up", "stopped"

    def _set_state(self, new_state: str) -> None:
        if self.state != new_state:
            self.state = new_state
            if self.on_state:
                try:
                    self.on_state(new_state)
                except Exception as exc:
                    logger.debug("on_state callback raised: %s", exc)

    def backoff_delay(self, attempt: int) -> float:
        """Compute exponential backoff delay for given retry attempt."""
        exponent = max(0, attempt - 1)
        delay = self.backoff_base * (2 ** exponent)
        return min(self.backoff_max, delay)

    def _default_log_file(self) -> Path:
        if self.log_file:
            return self.log_file
        local_app = os.environ.get("LOCALAPPDATA")
        base = Path(local_app) if local_app else Path.home() / ".elcagent"
        log_dir = base / "ElcAgent" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / "soapvoice.log"

    def _launch(self) -> bool:
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = CREATE_NO_WINDOW
            kwargs["close_fds"] = True

        log_path = self._default_log_file()
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = open(log_path, "a", encoding="utf-8")
            kwargs["stdout"] = log_handle
            kwargs["stderr"] = log_handle
        except Exception:
            pass

        try:
            self.proc = self.popen_factory([str(self.exe_path)], **kwargs)
            self.started_at = self.clock_fn()
            assign_kill_on_close_job(self.proc)
            logger.info("Launched SoapVoice child process: %s", self.exe_path)
            return True
        except Exception as exc:
            logger.error("Failed to launch SoapVoice %s: %s", self.exe_path, exc)
            self.proc = None
            return False

    def start(self) -> str:
        """Start or attach to SoapVoice."""
        # 1. External process check
        if self.health_fn and self.health_fn():
            self._set_state("external")
            return "external"

        # 2. Check executable existence
        if not self.exists_fn(self.exe_path):
            self._set_state("missing")
            return "missing"

        # 3. Launch process
        if self._launch():
            self._set_state("running")
            return "running"
        else:
            self.restart_count += 1
            self._set_state("restarting")
            return "restarting"

    def poll_once(self) -> str:
        """Poll child process health and handle restart logic."""
        if self.state == "stopped":
            return "stopped"

        if self.state == "gave_up":
            return "gave_up"

        # Check external health if child process not started by us
        if self.proc is None and self.health_fn and self.health_fn():
            self._set_state("external")
            return "external"

        if not self.exists_fn(self.exe_path):
            self._set_state("missing")
            return "missing"

        if self.proc is None:
            return self.start()

        # Check if process is still alive
        poll_res = self.proc.poll()
        if poll_res is None:
            # Process is running
            now = self.clock_fn()
            if (now - self.started_at) >= self.stable_seconds:
                if self.restart_count > 0:
                    logger.info("SoapVoice stable for %ss; resetting restart count", self.stable_seconds)
                    self.restart_count = 0
            self._set_state("running")
            return "running"

        # Process has terminated!
        logger.warning("SoapVoice process exited with code %s", poll_res)
        self.restart_count += 1

        if self.restart_count > self.max_restarts:
            logger.error("SoapVoice failed %d times (max %d). Giving up.", self.restart_count, self.max_restarts)
            self._set_state("gave_up")
            return "gave_up"

        delay = self.backoff_delay(self.restart_count)
        logger.info("Restarting SoapVoice in %.1fs (attempt %d/%d)", delay, self.restart_count, self.max_restarts)
        self.sleep_fn(delay)
        self._set_state("restarting")

        self._launch()
        return "restarting"

    def stop(self) -> None:
        """Terminate child process and transition to stopped state."""
        self._set_state("stopped")
        if self.proc:
            try:
                self.proc.terminate()
            except Exception as exc:
                logger.debug("Failed to terminate SoapVoice: %s", exc)

            # Wait or force kill
            if hasattr(self.proc, "poll"):
                for _ in range(50):
                    if self.proc.poll() is not None:
                        break
                    time.sleep(0.1)
                if self.proc.poll() is None and hasattr(self.proc, "kill"):
                    try:
                        self.proc.kill()
                    except Exception:
                        pass
            self.proc = None


def run_in_thread(
    supervisor: SoapVoiceSupervisor,
    interval: float = 5.0,
    stop_event: Optional[threading.Event] = None,
) -> threading.Thread:
    """Run supervisor.poll_once in a daemon thread until stop_event is set."""
    event = stop_event or threading.Event()

    def _worker():
        while not event.is_set():
            try:
                supervisor.poll_once()
            except Exception as exc:
                logger.error("Supervisor poll error: %s", exc)
            event.wait(timeout=interval)
        supervisor.stop()

    t = threading.Thread(target=_worker, name="SoapVoiceSupervisorThread", daemon=True)
    t.start()
    return t
