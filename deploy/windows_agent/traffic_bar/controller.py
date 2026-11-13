"""Phase 31: 快捷列通訊與流程控制器 (D-31-03, D-31-05 ~ D-31-08, D-31-11, D-31-12, D-31-16, D-31-24, D-31-33).

責任：
- 協調 SoapVoice 本機控制客戶端與 Server 客戶端
- 推進紅、綠、黃燈業務動作與狀態投影
- 處理失敗保留、離線容錯、心跳搭便車通知與確認視窗觸發
- 啟動重啟還原（Pitfall 8）
- 嚴格為純流程邏輯，不依賴任何 GUI 函式庫
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Dict, Optional, Set, Tuple
import uuid

from deploy.windows_agent.config import AgentSettings
from deploy.windows_agent.traffic_bar.bar_state import (
    STATE_ARCHIVE_FAILED,
    STATE_ARCHIVING,
    STATE_CONFIRMED,
    on_press,
    project,
    status_text,
)
from deploy.windows_agent.traffic_bar.server_client import (
    CycleServerClient,
    ServerRejected,
    ServerUnavailable,
)
from deploy.windows_agent.traffic_bar.soapvoice_client import (
    IpcRejected,
    IpcUnavailable,
    SoapVoiceControlClient,
)

logger = logging.getLogger("traffic_bar.controller")


class BarController:
    """快捷列業務與通訊協調控制器。"""

    def __init__(
        self,
        sv_client: SoapVoiceControlClient,
        server_client: CycleServerClient,
        settings: AgentSettings,
        *,
        open_confirm_window: Callable[[str], None],
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
        auto_recover: bool = True,
    ):
        self.sv_client = sv_client
        self.server_client = server_client
        self.settings = settings
        self.open_confirm_window = open_confirm_window
        self.clock = clock
        self.id_factory = id_factory

        # 內部狀態
        self.current_cycle: Optional[Dict[str, Any]] = None
        self.sv_status: Optional[Dict[str, Any]] = None
        self.server_online: bool = True
        self.sv_online: bool = True
        self.pending_action: Optional[str] = None
        self.last_toast: Optional[str] = None

        # 去重與排程補送
        self.notified_keys: Set[Tuple[str, Optional[str], Optional[int]]] = set()
        self.pending_server_stop: Optional[str] = None
        self.pending_archived_ack: Set[str] = set()

        if auto_recover:
            self.recover_on_startup()

    def recover_on_startup(self) -> None:
        """快捷列重啟時狀態還原 (Pitfall 8)."""
        # 1. 查詢 SoapVoice 狀態
        try:
            st = self.sv_client.status()
            self.sv_status = st
            self.sv_online = True
        except Exception as exc:
            logger.debug("啟動查詢 SoapVoice 狀態失敗: %s", exc)
            self.sv_online = False
            self.sv_status = None

        # 2. 查詢 Server 當前是否有未終結循環
        try:
            active = self.server_client.get_active(self.settings.machine_id)
            self.server_online = True
            if active:
                c_state = active.get("state")
                if c_state == "RECORDING":
                    sv_st = self.sv_status.get("state") if self.sv_status else None
                    sv_cid = self.sv_status.get("cycle_id") if self.sv_status else None
                    if sv_st == "RECORDING" and sv_cid == active.get("cycle_id"):
                        # 兩端皆在錄音中，接續既有循環，不重送紅燈
                        self.current_cycle = active
                    elif sv_st == "IDLE":
                        chunks_rcv = int(active.get("chunks_received") or 0)
                        if chunks_rcv == 0:
                            # 錄音未成功開啟，自動放棄
                            try:
                                self.server_client.abandon(active["cycle_id"], reason_code="start_incomplete")
                            except Exception:
                                pass
                            self.current_cycle = None
                        else:
                            # 已有分段送達但 SoapVoice 已停止，標記中斷供醫師介入
                            self.current_cycle = active
                    else:
                        self.current_cycle = active
                else:
                    self.current_cycle = active
        except Exception as exc:
            logger.debug("啟動查詢 Server 循環失敗: %s", exc)
            self.server_online = False

    @property
    def bar_state(self) -> str:
        """當前快捷列投影狀態。"""
        return project(
            self.current_cycle,
            self.sv_status,
            server_online=self.server_online,
            sv_online=self.sv_online,
            pending_action=self.pending_action,
        )

    @property
    def status(self) -> str:
        """當前快捷列狀態提示文字。"""
        return status_text(
            self.bar_state,
            sv_status=self.sv_status,
            server_cycle=self.current_cycle,
        )

    def on_red(self) -> bool:
        """紅燈：開始錄音 (D-31-05)."""
        allowed, toast = on_press("red", self.bar_state, pending_action=self.pending_action)
        if not allowed:
            self.last_toast = toast
            return False

        self.pending_action = "starting"
        cmd_id = self.id_factory()

        try:
            # 1. 先向 server 建立循環
            try:
                cycle = self.server_client.create_cycle(
                    cmd_id,
                    machine_id=self.settings.machine_id,
                    room_id=self.settings.room_id or None,
                )
                self.server_online = True
            except ServerRejected as exc:
                if exc.status == 409 and exc.body.get("error") == "active_cycle_exists":
                    # 採用既有未終結循環
                    active_cid = exc.body.get("active_cycle_id")
                    if active_cid:
                        cycle = self.server_client.get_cycle(active_cid)
                    else:
                        cycle = self.server_client.get_active(self.settings.machine_id)
                    self.current_cycle = cycle
                    self.last_toast = "已切換至既有進行中循環"
                    return True
                self.last_toast = f"伺服器建立循環失敗: {exc.message}"
                return False
            except ServerUnavailable as exc:
                self.server_online = False
                self.last_toast = "伺服器無法連線"
                return False

            cycle_id = cycle["cycle_id"]

            # 2. 以同一 cycle_id 指示 SoapVoice 開始錄音
            try:
                sv_resp = self.sv_client.start(cmd_id, cycle_id)
                self.sv_online = True
                self.sv_status = sv_resp
                self.current_cycle = cycle
                self.last_toast = "開始錄音"
                return True
            except (IpcRejected, IpcUnavailable) as exc:
                if isinstance(exc, IpcUnavailable):
                    self.sv_online = False
                # SoapVoice 啟動失敗時，放棄剛建立之 server 循環
                try:
                    self.server_client.abandon(cycle_id, reason_code="start_failed")
                except Exception:
                    pass
                self.current_cycle = None
                self.last_toast = "麥克風或 SoapVoice 啟動失敗"
                return False
        finally:
            self.pending_action = None

    def on_green(self) -> bool:
        """綠燈：結束錄音 (D-31-07)."""
        allowed, toast = on_press("green", self.bar_state, pending_action=self.pending_action)
        if not allowed:
            self.last_toast = toast
            return False

        if not self.current_cycle:
            self.last_toast = "無進行中循環"
            return False

        cycle_id = self.current_cycle["cycle_id"]
        cmd_id = self.id_factory()
        self.pending_action = "stopping"

        try:
            # 1. 先指示 SoapVoice 停止
            try:
                sv_resp = self.sv_client.stop(cmd_id, cycle_id)
                self.sv_online = True
                self.sv_status = sv_resp
            except (IpcRejected, IpcUnavailable) as exc:
                if isinstance(exc, IpcUnavailable):
                    self.sv_online = False
                self.last_toast = "SoapVoice 停止錄音失敗"
                return False

            # 2. 通知 server stop
            try:
                cycle = self.server_client.stop(cycle_id, cmd_id)
                self.server_online = True
                self.current_cycle = cycle
                self.last_toast = "已停止錄音，上傳中..."
                return True
            except ServerUnavailable:
                self.server_online = False
                self.pending_server_stop = cycle_id
                self.last_toast = "伺服器無法連線，已停止本機錄音並排程補送"
                return True
            except ServerRejected as exc:
                self.last_toast = f"伺服器停止失敗: {exc.message}"
                return False
        finally:
            self.pending_action = None

    def on_yellow(self) -> bool:
        """黃燈：封存與 HIS 寫入 (D-31-06, D-31-07)."""
        allowed, toast = on_press("yellow", self.bar_state, pending_action=self.pending_action)
        if not allowed:
            self.last_toast = toast
            return False

        if not self.current_cycle:
            self.last_toast = "目前無可封存循環"
            return False

        cycle_id = self.current_cycle["cycle_id"]
        cmd_id = self.id_factory()
        self.pending_action = "archiving"

        try:
            status_code, body = self.server_client.archive(cycle_id, cmd_id)
            self.server_online = True
            if status_code == 200:
                self.current_cycle = None
                self.pending_action = None
                self.last_toast = "封存成功"
                try:
                    self.sv_client.archived(cycle_id)
                    self.sv_online = True
                except Exception:
                    self.pending_archived_ack.add(cycle_id)
                return True
            elif status_code == 202:
                self.pending_action = "archiving"
                self.last_toast = "HIS 寫入處理中..."
                return True
            elif status_code == 409:
                self.pending_action = None
                if self.current_cycle:
                    self.current_cycle["state"] = STATE_ARCHIVE_FAILED
                reason = body.get("reason") or body.get("status") or "未知原因"
                self.last_toast = f"封存失敗：{reason}"
                return False
            else:
                self.pending_action = None
                self.last_toast = f"封存回應未預期狀態 ({status_code})"
                return False
        except ServerUnavailable:
            self.server_online = False
            self.pending_action = "archiving"
            self.last_toast = "伺服器暫時無法連線，將自動重試"
            return False
        except ServerRejected as exc:
            self.pending_action = None
            if self.current_cycle:
                self.current_cycle["state"] = STATE_ARCHIVE_FAILED
            self.last_toast = f"封存失敗: {exc.message}"
            return False

    def on_confirm_save(
        self,
        cycle_id: str,
        content_hash: str,
        soap: Optional[Dict[str, Any]] = None,
        reviewer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """醫師在確認視窗確認存檔 (D-31-08)."""
        res = self.server_client.confirm(
            cycle_id,
            content_hash=content_hash,
            soap=soap,
            reviewer_id=reviewer_id,
        )
        if self.current_cycle and self.current_cycle.get("cycle_id") == cycle_id:
            self.current_cycle["state"] = STATE_CONFIRMED
        return res

    def tick_soapvoice(self) -> None:
        """每秒輪詢一次 SoapVoice 狀態與處理補送 (契約 §1)."""
        try:
            st = self.sv_client.status()
            self.sv_status = st
            self.sv_online = True
        except (IpcUnavailable, IpcRejected) as exc:
            if isinstance(exc, IpcUnavailable):
                self.sv_online = False
            return

        # 處理 pending_archived_ack
        if self.pending_archived_ack:
            for cid in list(self.pending_archived_ack):
                try:
                    self.sv_client.archived(cid)
                    self.pending_archived_ack.discard(cid)
                except Exception:
                    pass

    def tick_server(self) -> None:
        """每 5 秒發送心跳、處理搭便車通知與自動重試 (契約 §3, D-31-12)."""
        b_state = self.bar_state
        sv_st = self.sv_status.get("state") if self.sv_status else None
        chunks_pending = int(self.sv_status.get("chunks_pending") or 0) if self.sv_status else None

        # 1. 心跳回報
        try:
            hb = self.server_client.heartbeat(
                machine_id=self.settings.machine_id,
                machine_name=getattr(self.settings, "app_name", None),
                room_id=self.settings.room_id or None,
                bar_state=b_state,
                soapvoice_state=sv_st,
                chunks_pending=chunks_pending,
                app_version=str(getattr(self.settings, "schema_version", 1)),
            )
            self.server_online = True
        except ServerUnavailable:
            self.server_online = False
            return
        except Exception:
            return

        # 2. 補送 pending_server_stop
        if self.pending_server_stop:
            try:
                cmd_id = self.id_factory()
                c = self.server_client.stop(self.pending_server_stop, cmd_id)
                self.pending_server_stop = None
                if self.current_cycle and self.current_cycle.get("cycle_id") == c.get("cycle_id"):
                    self.current_cycle = c
            except Exception:
                pass

        # 3. 處理搭便車通知
        notify = hb.get("notify")
        if notify:
            notify_cid = notify.get("cycle_id")
            notify_state = notify.get("state")
            draft_id = notify.get("draft_id")
            draft_version = notify.get("draft_version")

            if self.current_cycle and self.current_cycle.get("cycle_id") == notify_cid:
                self.current_cycle["state"] = notify_state
                if draft_id:
                    self.current_cycle["draft_id"] = draft_id
            elif not self.current_cycle and notify_cid:
                try:
                    self.current_cycle = self.server_client.get_cycle(notify_cid)
                except Exception:
                    pass

            if notify_state in ("AWAITING_CONFIRM", "DRAFT_UNUSABLE"):
                key = (notify_cid, draft_id, draft_version)
                if key not in self.notified_keys:
                    self.notified_keys.add(key)
                    try:
                        self.open_confirm_window(notify_cid)
                    except Exception as exc:
                        logger.error("呼叫 open_confirm_window 失敗: %s", exc)

        # 4. 自動重試 archive
        should_retry_archive = (
            self.pending_action == "archiving"
            or (self.current_cycle and self.current_cycle.get("state") == STATE_ARCHIVING)
        )
        if should_retry_archive and self.current_cycle:
            cid = self.current_cycle["cycle_id"]
            cmd_id = self.id_factory()
            try:
                status_code, body = self.server_client.archive(cid, cmd_id)
                if status_code == 200:
                    self.pending_action = None
                    self.current_cycle = None
                    self.last_toast = "封存成功"
                    try:
                        self.sv_client.archived(cid)
                    except Exception:
                        self.pending_archived_ack.add(cid)
                elif status_code == 409:
                    self.pending_action = None
                    if self.current_cycle:
                        self.current_cycle["state"] = STATE_ARCHIVE_FAILED
                    reason = body.get("reason") or "HIS 寫入失敗"
                    self.last_toast = f"封存失敗：{reason}"
            except Exception:
                pass
