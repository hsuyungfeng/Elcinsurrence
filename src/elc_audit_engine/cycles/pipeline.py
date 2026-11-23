"""循環音訊 finalize 後之自動背景管線：本機 ASR → Gemma 4 E4B 臨床 SOAP 草稿。

職責與設計原則：
- 由 ``POST /api/cycles/<cycle_id>/finalize`` 成功產出 ``full.wav`` 後以 daemon 背景執行緒觸發。
- 串接既有元件：``transcribe_audio()``（預設 sherpa-onnx SenseVoice int8 + OpenCC + 熱詞，
  可透過 ``ELC_ASR_DIARIZE=1`` 啟用 ``num_clusters=2`` 雙人說者分離）→
  ``generate_clinical_soap_from_transcript()``（Gemma 4 E4B clinical profile）→
  ``submit_cycle_draft()``（寫入 ``transcript.txt``、品質檢核並轉入 ``AWAITING_CONFIRM``
  或 ``DRAFT_UNUSABLE``）。
- **系統故障語意（絕不偽造業務結論）**：
  - ASR 不可用／轉錄失敗／空逐字稿／LLM 連線失敗或回傳無法解析時，絕不寫入假 SOAP；
    僅記錄純系統錯誤摘要至 ``recording_cycles.last_error``，維持原等待狀態（不誤轉無
    ``draft_id`` 之 ``DRAFT_UNUSABLE``，以免確認視窗讀取 ``/draft`` 404）。
  - 若 ASR 已產出逐字稿但 LLM 失敗，仍原子保存 ``transcript.txt`` 並更新 ``transcript_path``。
- **競態與冪等保護**：
  - 行程內 ``_INFLIGHT_CYCLES`` 防止同一 ``cycle_id`` 重複啟動背景執行緒。
  - 若在執行前或送出草稿前，該循環已被手動送入草稿（``draft_id`` 非空）或已進入終態
    （``ABANDONED``／``ARCHIVED`` 等），則優雅跳過（no-op），絕不覆蓋。
- **PHI-safe logging**：所有日誌與 ``last_error`` 嚴禁含逐字稿、SOAP 內文或病患個資。
- **D-31-29**：絕不刪除任何音檔或分段檔。
"""

from __future__ import annotations

import datetime
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from elc_audit_engine.asr.transcriber import (
    ASRTranscriptionError,
    ASRUnavailableError,
    TranscriptionResult,
    transcribe_audio,
)
from elc_audit_engine.comparator.soap_advice import generate_clinical_soap_from_transcript
from elc_audit_engine.cycles.drafts import submit_cycle_draft
from elc_audit_engine.cycles.states import (
    STATE_AWAITING_DRAFT,
    STATE_DRAFT_UNUSABLE,
    STATE_RECORDING,
    IllegalCycleTransitionError,
)
from elc_audit_engine.cycles.store import cycle_dir, transition_cycle

logger = logging.getLogger(__name__)

_DEFAULT_ACTOR = "system:auto-pipeline"
_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT_CYCLES: set[str] = set()
_ELIGIBLE_STATES = frozenset({STATE_RECORDING, STATE_AWAITING_DRAFT, STATE_DRAFT_UNUSABLE})
_LOW_DENSITY_MIN_DURATION_S = 60.0
_FALLBACK_GAIN_FACTOR = 1.25
_FALLBACK_MAX_REPETITION_RATIO = 0.15


def _transcript_repetition_ratio(text: str, *, window: int = 8) -> float:
    """計算逐字稿重複視窗占比（去空白後步長 1 之連續 window 字元滑動視窗）。

    公式：``round(1.0 - len(set(windows)) / len(windows), 4)``，範圍 ``[0.0, 1.0)``。
    長度不足 ``window`` 時回傳 ``0.0``。用於防止 Whisper 重複迴圈灌水字數。
    """
    cleaned = re.sub(r"\s+", "", text or "")
    if len(cleaned) < window or window <= 0:
        return 0.0
    windows = [cleaned[i : i + window] for i in range(len(cleaned) - window + 1)]
    return round(1.0 - (len(set(windows)) / len(windows)), 4)


def _maybe_whisper_low_density_fallback(
    audio_path: Path,
    asr_result: TranscriptionResult,
    *,
    cycle_id: str,
    fallback_transcriber: Optional[Callable[[Path], TranscriptionResult]] = None,
) -> TranscriptionResult:
    """選配低字數密度 Whisper 備援（預設關閉；須 ≥1.25× 有效字數且重複率 <0.15 才採用）。"""
    if not _parse_bool_env("ELC_ASR_LOW_DENSITY_WHISPER_FALLBACK", default=False):
        return asr_result
    if "sherpa" not in (asr_result.model or "").lower():
        return asr_result
    if asr_result.duration_s < _LOW_DENSITY_MIN_DURATION_S:
        return asr_result

    try:
        min_cpm = float(os.environ.get("ELC_ASR_MIN_CHARS_PER_MIN", "60"))
    except ValueError:
        min_cpm = 60.0

    base_no_tags = re.sub(r"\[Speaker\s+\d+\]", "", asr_result.transcript or "")
    base_chars = len(re.sub(r"\s+", "", base_no_tags))
    cpm = base_chars / (asr_result.duration_s / 60.0)
    if cpm >= min_cpm:
        return asr_result

    logger.info(
        "Auto pipeline low transcript density detected: cycle_id=%s duration_s=%.1f cpm=%.1f threshold=%.1f",
        cycle_id,
        asr_result.duration_s,
        cpm,
        min_cpm,
    )
    run_fb = fallback_transcriber or (lambda p: transcribe_audio(p, backend="whisper"))
    try:
        fb_result = run_fb(audio_path)
    except (ASRUnavailableError, ASRTranscriptionError) as exc:
        logger.warning(
            "Auto pipeline Whisper fallback unavailable/failed (keeping primary): cycle_id=%s err=%s",
            cycle_id,
            type(exc).__name__,
        )
        return asr_result
    except Exception as exc:
        logger.warning(
            "Auto pipeline Whisper fallback error (keeping primary): cycle_id=%s err=%s",
            cycle_id,
            type(exc).__name__,
        )
        return asr_result

    fb_text = (fb_result.transcript or "").strip()
    fb_chars = len(re.sub(r"\s+", "", fb_text))
    rep_ratio = _transcript_repetition_ratio(fb_text)
    if fb_chars > 0 and fb_chars >= base_chars * _FALLBACK_GAIN_FACTOR and rep_ratio < _FALLBACK_MAX_REPETITION_RATIO:
        logger.info(
            "Auto pipeline adopted Whisper fallback: cycle_id=%s primary_chars=%d fallback_chars=%d rep_ratio=%.4f",
            cycle_id,
            base_chars,
            fb_chars,
            rep_ratio,
        )
        return fb_result

    logger.info(
        "Auto pipeline rejected Whisper fallback (keeping primary): cycle_id=%s primary_chars=%d fallback_chars=%d rep_ratio=%.4f",
        cycle_id,
        base_chars,
        fb_chars,
        rep_ratio,
    )
    return asr_result


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def is_auto_pipeline_enabled(*, app_config: Optional[Dict[str, Any]] = None) -> bool:
    """判斷是否啟用 finalize 後之自動 ASR → SOAP 背景管線。

    優先順序：
    1. ``app_config["ELC_CYCLE_AUTO_PIPELINE"]``（若明確設定）
    2. 若 ``app_config["TESTING"]`` 為 True 且未明確設定上述鍵，預設為 False（避免單元測試誤觸外部模型／LLM）
    3. 環境變數 ``ELC_CYCLE_AUTO_PIPELINE``（預設 True）
    """
    if app_config is not None:
        if "ELC_CYCLE_AUTO_PIPELINE" in app_config and app_config["ELC_CYCLE_AUTO_PIPELINE"] is not None:
            return bool(app_config["ELC_CYCLE_AUTO_PIPELINE"])
        if app_config.get("TESTING"):
            return False
    return _parse_bool_env("ELC_CYCLE_AUTO_PIPELINE", default=True)


def _read_cycle_row(store, cycle_id: str) -> Optional[Dict[str, Any]]:
    conn = store._connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT cycle_id, state, upload_complete, audio_path, draft_id, session_id "
            "FROM recording_cycles WHERE cycle_id = ?",
            (cycle_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _record_pipeline_failure(
    store,
    cycle_id: str,
    error_summary: str,
    *,
    transcript_path: Optional[str] = None,
) -> None:
    """以交易安全方式記錄純系統錯誤摘要至 ``last_error``（必要時附帶 ``transcript_path``）。"""
    now = _now_iso()
    conn = store._connect()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.cursor()
            if transcript_path is not None:
                cur.execute(
                    "UPDATE recording_cycles SET last_error = ?, transcript_path = ?, updated_at = ? "
                    "WHERE cycle_id = ? AND draft_id IS NULL",
                    (error_summary, transcript_path, now, cycle_id),
                )
            else:
                cur.execute(
                    "UPDATE recording_cycles SET last_error = ?, updated_at = ? "
                    "WHERE cycle_id = ? AND draft_id IS NULL",
                    (error_summary, now, cycle_id),
                )
    finally:
        conn.close()


def _save_transcript_atomic(cycle_id: str, transcript: str) -> Path:
    """原子寫入逐字稿至 ``<DATA_DIR>/cycles/<cycle_id>/transcript.txt``。"""
    c_dir = cycle_dir(cycle_id)
    c_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = c_dir / f"transcript.txt.tmp.{uuid.uuid4().hex[:8]}"
    target_path = c_dir / "transcript.txt"
    try:
        tmp_path.write_text(transcript, encoding="utf-8")
        os.replace(tmp_path, target_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
    return target_path


def run_cycle_auto_pipeline(
    store,
    cycle_id: str,
    *,
    diarize: Optional[bool] = None,
    actor: str = _DEFAULT_ACTOR,
    transcriber: Optional[Callable[..., TranscriptionResult]] = None,
    fallback_transcriber: Optional[Callable[[Path], TranscriptionResult]] = None,
    soap_generator: Optional[Callable[[str], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """同步執行單一循環的 ASR → Gemma 4 E4B 臨床 SOAP → 草稿送出管線。

    Args:
        store: CaseStore 實例。
        cycle_id: 已完成 finalize 的循環 ID。
        diarize: 是否啟用說者分離（未指定時讀取 ``ELC_ASR_DIARIZE``，預設 False）。
        actor: 審計／狀態轉換操作者識別字。
        transcriber: 可選 ASR 注入點（預設 ``transcribe_audio``）。
        soap_generator: 可選 SOAP 生成注入點（預設 ``generate_clinical_soap_from_transcript``）。

    Returns:
        不含 PHI 的執行摘要字典（``status`` 為 ``"completed"`` / ``"skipped"`` / ``"error"``）。
    """
    t0 = time.monotonic()
    row = _read_cycle_row(store, cycle_id)
    if not row:
        logger.warning("Auto pipeline skipped: cycle_id=%s reason=not_found", cycle_id)
        return {"status": "skipped", "cycle_id": cycle_id, "reason": "not_found"}

    if row["draft_id"]:
        logger.info("Auto pipeline skipped: cycle_id=%s reason=draft_exists", cycle_id)
        return {"status": "skipped", "cycle_id": cycle_id, "reason": "draft_exists"}

    if not bool(row["upload_complete"]) or not row["audio_path"]:
        logger.warning("Auto pipeline skipped: cycle_id=%s reason=upload_incomplete", cycle_id)
        return {"status": "skipped", "cycle_id": cycle_id, "reason": "upload_incomplete"}

    if row["state"] not in _ELIGIBLE_STATES:
        logger.info("Auto pipeline skipped: cycle_id=%s reason=ineligible_state state=%s", cycle_id, row["state"])
        return {"status": "skipped", "cycle_id": cycle_id, "reason": "ineligible_state", "state": row["state"]}

    audio_path = Path(row["audio_path"])
    if not audio_path.is_file():
        err = "ASR_AUDIO_MISSING: 找不到合併後的音檔"
        _record_pipeline_failure(store, cycle_id, err)
        logger.warning("Auto pipeline failed: cycle_id=%s code=ASR_AUDIO_MISSING", cycle_id)
        return {"status": "error", "cycle_id": cycle_id, "error_code": "ASR_AUDIO_MISSING"}

    eff_diarize = _parse_bool_env("ELC_ASR_DIARIZE", default=False) if diarize is None else bool(diarize)
    run_asr = transcriber or transcribe_audio
    run_soap = soap_generator or generate_clinical_soap_from_transcript

    # 1. 本機 ASR 轉錄（含選配低密度 Whisper 備援與重複率護欄）
    try:
        asr_result = run_asr(audio_path, diarize=eff_diarize)
    except ASRUnavailableError as exc:
        err = f"ASR_UNAVAILABLE: {type(exc).__name__}"
        _record_pipeline_failure(store, cycle_id, err)
        logger.warning("Auto pipeline failed: cycle_id=%s code=ASR_UNAVAILABLE err=%s", cycle_id, type(exc).__name__)
        return {"status": "error", "cycle_id": cycle_id, "error_code": "ASR_UNAVAILABLE"}
    except ASRTranscriptionError as exc:
        err = f"ASR_FAILED: {type(exc).__name__}"
        _record_pipeline_failure(store, cycle_id, err)
        logger.warning("Auto pipeline failed: cycle_id=%s code=ASR_FAILED err=%s", cycle_id, type(exc).__name__)
        return {"status": "error", "cycle_id": cycle_id, "error_code": "ASR_FAILED"}
    except Exception as exc:
        err = f"ASR_ERROR: {type(exc).__name__}"
        _record_pipeline_failure(store, cycle_id, err)
        logger.warning("Auto pipeline failed: cycle_id=%s code=ASR_ERROR err=%s", cycle_id, type(exc).__name__)
        return {"status": "error", "cycle_id": cycle_id, "error_code": "ASR_ERROR"}

    asr_result = _maybe_whisper_low_density_fallback(
        audio_path,
        asr_result,
        cycle_id=cycle_id,
        fallback_transcriber=fallback_transcriber,
    )

    transcript = (asr_result.transcript or "").strip()
    if not transcript:
        err = "TRANSCRIPT_EMPTY: 語音轉錄結果為空，未產生草稿"
        _record_pipeline_failure(store, cycle_id, err)
        logger.warning("Auto pipeline failed: cycle_id=%s code=TRANSCRIPT_EMPTY", cycle_id)
        return {"status": "error", "cycle_id": cycle_id, "error_code": "TRANSCRIPT_EMPTY"}

    # 在呼叫 LLM 前先檢查循環是否已中止或已有手動草稿，避免白跑 LLM
    pre_llm_row = _read_cycle_row(store, cycle_id)
    if not pre_llm_row or pre_llm_row["draft_id"] or pre_llm_row["state"] not in _ELIGIBLE_STATES:
        logger.info("Auto pipeline skipped before LLM: cycle_id=%s", cycle_id)
        return {"status": "skipped", "cycle_id": cycle_id, "reason": "state_changed_before_llm"}

    # 2. Gemma 4 E4B 臨床 SOAP 生成
    try:
        soap_res = run_soap(transcript)
    except Exception as exc:
        t_path = _save_transcript_atomic(cycle_id, transcript)
        err = f"LLM_ERROR: {type(exc).__name__}"
        _record_pipeline_failure(store, cycle_id, err, transcript_path=str(t_path))
        logger.warning("Auto pipeline failed: cycle_id=%s code=LLM_ERROR err=%s", cycle_id, type(exc).__name__)
        return {"status": "error", "cycle_id": cycle_id, "error_code": "LLM_ERROR"}

    soap_status = (soap_res or {}).get("status")
    soap_dict = (soap_res or {}).get("soap")
    if soap_status != "success" or not isinstance(soap_dict, dict) or not all(
        isinstance(soap_dict.get(k), str) for k in ("s", "o", "a", "p")
    ):
        t_path = _save_transcript_atomic(cycle_id, transcript)
        err_code = "LLM_INVALID_JSON" if soap_status == "fallback" else "LLM_ERROR"
        err = f"{err_code}: LLM 未產出合法結構化 SOAP"
        _record_pipeline_failure(store, cycle_id, err, transcript_path=str(t_path))
        logger.warning("Auto pipeline failed: cycle_id=%s code=%s soap_status=%s", cycle_id, err_code, soap_status)
        return {"status": "error", "cycle_id": cycle_id, "error_code": err_code}

    # 3. 送出草稿前最後狀態確認（若仍在 RECORDING 則合法轉入 AWAITING_DRAFT）
    latest = _read_cycle_row(store, cycle_id)
    if not latest or latest["draft_id"] or latest["state"] not in _ELIGIBLE_STATES:
        logger.info("Auto pipeline skipped before submit: cycle_id=%s", cycle_id)
        return {"status": "skipped", "cycle_id": cycle_id, "reason": "state_changed_before_submit"}

    if latest["state"] == STATE_RECORDING:
        try:
            transition_cycle(
                store,
                cycle_id,
                STATE_AWAITING_DRAFT,
                actor=actor,
                reason_code="auto_finalize_to_draft",
                expect_from=STATE_RECORDING,
            )
        except IllegalCycleTransitionError:
            latest = _read_cycle_row(store, cycle_id)
            if not latest or latest["draft_id"] or latest["state"] not in (STATE_AWAITING_DRAFT, STATE_DRAFT_UNUSABLE):
                logger.info("Auto pipeline skipped after race: cycle_id=%s", cycle_id)
                return {"status": "skipped", "cycle_id": cycle_id, "reason": "state_changed_after_race"}

    icd_checks = (soap_res or {}).get("icd10_checks") or []
    icd10_codes = [c["code"] for c in icd_checks if isinstance(c, dict) and c.get("code")]

    draft_payload: Dict[str, Any] = {
        "session_id": f"auto_{cycle_id[:24]}",
        "soap": {k: soap_dict[k] for k in ("s", "o", "a", "p")},
        "transcript": transcript,
        "extras": {
            "summary_zh": str((soap_res or {}).get("conversation_summary") or "")[:20000],
            "asr_model": asr_result.model,
            "asr_duration_s": asr_result.duration_s,
            "asr_elapsed_s": asr_result.elapsed_s,
            "suggestions": {
                "icd10": icd10_codes[:200],
            },
        },
    }

    try:
        updated_cycle, draft_id, created = submit_cycle_draft(
            store,
            cycle_id=cycle_id,
            payload=draft_payload,
            actor=actor,
        )
    except Exception as exc:
        err = f"DRAFT_SUBMIT_ERROR: {type(exc).__name__}"
        _record_pipeline_failure(store, cycle_id, err)
        logger.warning("Auto pipeline submit failed: cycle_id=%s err=%s", cycle_id, type(exc).__name__)
        return {"status": "error", "cycle_id": cycle_id, "error_code": "DRAFT_SUBMIT_ERROR"}

    total_elapsed = round(time.monotonic() - t0, 2)
    logger.info(
        "Auto pipeline completed: cycle_id=%s draft_id=%s state=%s created=%s asr_model=%s elapsed_s=%.2f",
        cycle_id,
        draft_id,
        updated_cycle.get("state"),
        created,
        asr_result.model,
        total_elapsed,
    )
    return {
        "status": "completed",
        "cycle_id": cycle_id,
        "draft_id": draft_id,
        "state": updated_cycle.get("state"),
        "created": created,
        "asr_model": asr_result.model,
        "elapsed_s": total_elapsed,
    }


def schedule_cycle_auto_pipeline(
    store,
    cycle_id: str,
    *,
    diarize: Optional[bool] = None,
    actor: str = _DEFAULT_ACTOR,
    runner: Optional[Callable[[Any, str], Any]] = None,
) -> bool:
    """以背景 daemon 執行緒排程自動 ASR → SOAP 管線（防同一 cycle_id 重複排程）。

    Returns:
        True 表示本次成功排入背景執行；False 表示該 cycle_id 已在執行中而略過。
    """
    with _INFLIGHT_LOCK:
        if cycle_id in _INFLIGHT_CYCLES:
            logger.info("Auto pipeline already in-flight: cycle_id=%s", cycle_id)
            return False
        _INFLIGHT_CYCLES.add(cycle_id)

    def _worker() -> None:
        try:
            if runner is not None:
                runner(store, cycle_id)
            else:
                run_cycle_auto_pipeline(store, cycle_id, diarize=diarize, actor=actor)
        except Exception as exc:
            logger.warning(
                "Unhandled exception in auto pipeline worker: cycle_id=%s err=%s",
                cycle_id,
                type(exc).__name__,
            )
        finally:
            with _INFLIGHT_LOCK:
                _INFLIGHT_CYCLES.discard(cycle_id)

    thread = threading.Thread(
        target=_worker,
        name=f"cycle-auto-pipeline-{cycle_id[:8]}",
        daemon=True,
    )
    thread.start()
    return True
