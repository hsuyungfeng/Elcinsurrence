"""測試 finalize 後自動背景 ASR → Gemma 4 E4B SOAP 管線。"""

from __future__ import annotations

import threading
import time

from elc_audit_engine.asr.transcriber import (
    ASRTranscriptionError,
    ASRUnavailableError,
    TranscriptionResult,
)
from elc_audit_engine.cycles.chunks import finalize_cycle_audio, store_chunk
from elc_audit_engine.cycles.drafts import cycle_draft_view, submit_cycle_draft
from elc_audit_engine.cycles.pipeline import (
    _transcript_repetition_ratio,
    is_auto_pipeline_enabled,
    run_cycle_auto_pipeline,
    schedule_cycle_auto_pipeline,
)
from elc_audit_engine.cycles.states import (
    STATE_ABANDONED,
    STATE_AWAITING_CONFIRM,
    STATE_AWAITING_DRAFT,
    STATE_DRAFT_UNUSABLE,
    STATE_RECORDING,
)
from elc_audit_engine.cycles.store import create_cycle, cycle_dir, get_cycle, transition_cycle
from tests.phase31_support import make_wav_chunk, pcm_sha256, wav_sha256
from tests.phase31_support import phase31_app, phase31_client  # noqa: F401

SOAP_OK = {
    "s": "Patient reports three days of sore throat, rhinorrhea, and mild dry cough without dyspnea or chest pain.",
    "o": "Alert and oriented. Oropharynx mildly erythematous without exudates. Bilateral lungs clear to auscultation.",
    "a": "Acute viral nasopharyngitis (J00).",
    "p": "Supportive hydration, acetaminophen 500 mg PRN fever or pain, return if symptoms worsen after five days.",
}
SOAP_BAD = {"s": "short", "o": "short", "a": "short", "p": "short"}


def _prepare_finalized_cycle(store, *, cmd_suffix: str, stop_before_finalize: bool = True) -> str:
    cycle, _ = create_cycle(
        store,
        command_id=f"cmd{cmd_suffix:0>29}",
        machine_id=f"m_{cmd_suffix}",
    )
    cid = cycle["cycle_id"]
    if stop_before_finalize:
        transition_cycle(store, cid, STATE_AWAITING_DRAFT, actor="test")
    chunk = make_wav_chunk(seconds=0.3, seed=int(cmd_suffix) if cmd_suffix.isdigit() else 1)
    store_chunk(store, cycle_id=cid, seq=0, declared_sha256=wav_sha256(chunk), data=chunk)
    finalize_cycle_audio(store, cycle_id=cid, total_chunks=1, audio_sha256=pcm_sha256([chunk]))
    return cid


def _fake_asr_ok(transcript: str = "醫師：哪裡不舒服？病人：喉嚨痛三天。") -> callable:
    def _fn(audio_path, *, diarize=False):
        return TranscriptionResult(
            transcript=transcript,
            model="sherpa-onnx-sensevoice-int8+diar" if diarize else "sherpa-onnx-sensevoice-int8",
            duration_s=12.5,
            elapsed_s=0.3,
            segment_count=2,
        )

    return _fn


def _fake_soap_ok(soap: dict | None = None) -> callable:
    payload = soap or SOAP_OK

    def _fn(transcript: str):
        return {
            "status": "success",
            "soap": payload,
            "conversation_summary": "病人主訴喉嚨痛三天併流鼻水，評估為急性鼻咽炎，給予症狀治療衛教。",
            "icd10_checks": [{"code": "J00", "valid": True}],
        }

    return _fn


def test_run_pipeline_success_from_awaiting_draft(phase31_app):  # noqa: F811
    """AWAITING_DRAFT + 完整錄音 → 轉錄 + 生成合格 SOAP → AWAITING_CONFIRM 並寫入逐字稿與建議。"""
    store = phase31_app.case_store
    cid = _prepare_finalized_cycle(store, cmd_suffix="1", stop_before_finalize=True)

    res = run_cycle_auto_pipeline(
        store,
        cid,
        transcriber=_fake_asr_ok(),
        soap_generator=_fake_soap_ok(),
    )
    assert res["status"] == "completed"
    assert res["state"] == STATE_AWAITING_CONFIRM
    assert res["draft_id"]

    cycle = get_cycle(store, cid)
    assert cycle["state"] == STATE_AWAITING_CONFIRM
    assert cycle["last_error"] is None

    view = cycle_draft_view(store, cid, include_transcript=True)
    assert view["draft"]["soap"] == SOAP_OK
    assert view["transcript"] == "醫師：哪裡不舒服？病人：喉嚨痛三天。"
    assert view["extras"]["asr_model"] == "sherpa-onnx-sensevoice-int8"
    assert view["extras"]["suggestions"]["icd10"] == ["J00"]
    assert "喉嚨痛" in view["extras"]["summary_zh"]


def test_run_pipeline_auto_stops_from_recording_state(phase31_app):  # noqa: F811
    """若 finalize 時仍在 RECORDING，管線自動合法轉入 AWAITING_DRAFT 再進 AWAITING_CONFIRM。"""
    store = phase31_app.case_store
    cid = _prepare_finalized_cycle(store, cmd_suffix="2", stop_before_finalize=False)
    assert get_cycle(store, cid)["state"] == STATE_RECORDING

    res = run_cycle_auto_pipeline(
        store,
        cid,
        diarize=True,
        transcriber=_fake_asr_ok(),
        soap_generator=_fake_soap_ok(),
    )
    assert res["status"] == "completed"
    assert res["state"] == STATE_AWAITING_CONFIRM
    assert res["asr_model"] == "sherpa-onnx-sensevoice-int8+diar"


def test_run_pipeline_quality_failed_transitions_to_draft_unusable(phase31_app):  # noqa: F811
    """LLM 產出但未通過 clinical 品質檢核 → 仍建立 draft 並轉 DRAFT_UNUSABLE 供醫師修改。"""
    store = phase31_app.case_store
    cid = _prepare_finalized_cycle(store, cmd_suffix="3", stop_before_finalize=True)

    res = run_cycle_auto_pipeline(
        store,
        cid,
        transcriber=_fake_asr_ok(),
        soap_generator=_fake_soap_ok(SOAP_BAD),
    )
    assert res["status"] == "completed"
    assert res["state"] == STATE_DRAFT_UNUSABLE
    view = cycle_draft_view(store, cid, include_transcript=True)
    assert view["draft"]["state"] == "quality_failed"
    assert view["transcript"]


def test_run_pipeline_asr_unavailable_fails_closed_without_fake_draft(phase31_app):  # noqa: F811
    """ASRUnavailableError 屬於系統故障：維持原狀態、記錄 last_error、絕不偽造草稿。"""
    store = phase31_app.case_store
    cid = _prepare_finalized_cycle(store, cmd_suffix="4", stop_before_finalize=True)

    def _boom(audio_path, *, diarize=False):
        raise ASRUnavailableError("sherpa-onnx missing")

    res = run_cycle_auto_pipeline(store, cid, transcriber=_boom, soap_generator=_fake_soap_ok())
    assert res["status"] == "error"
    assert res["error_code"] == "ASR_UNAVAILABLE"

    cycle = get_cycle(store, cid)
    assert cycle["state"] == STATE_AWAITING_DRAFT
    assert cycle["draft_id"] is None
    assert "ASR_UNAVAILABLE" in (cycle["last_error"] or "")


def test_run_pipeline_asr_transcription_error_and_empty_transcript(phase31_app):  # noqa: F811
    """ASRTranscriptionError 與空逐字稿皆記錄 last_error 且不建立假草稿。"""
    store = phase31_app.case_store
    cid_err = _prepare_finalized_cycle(store, cmd_suffix="5", stop_before_finalize=True)

    def _fail(audio_path, *, diarize=False):
        raise ASRTranscriptionError("decode error")

    r_err = run_cycle_auto_pipeline(store, cid_err, transcriber=_fail, soap_generator=_fake_soap_ok())
    assert r_err["error_code"] == "ASR_FAILED"
    assert get_cycle(store, cid_err)["draft_id"] is None
    assert "ASR_FAILED" in (get_cycle(store, cid_err)["last_error"] or "")

    cid_empty = _prepare_finalized_cycle(store, cmd_suffix="6", stop_before_finalize=True)
    r_empty = run_cycle_auto_pipeline(
        store,
        cid_empty,
        transcriber=_fake_asr_ok("   "),
        soap_generator=_fake_soap_ok(),
    )
    assert r_empty["error_code"] == "TRANSCRIPT_EMPTY"
    assert get_cycle(store, cid_empty)["draft_id"] is None
    assert "TRANSCRIPT_EMPTY" in (get_cycle(store, cid_empty)["last_error"] or "")


def test_run_pipeline_llm_error_preserves_transcript_and_clears_on_later_submit(phase31_app):  # noqa: F811
    """LLM 連線失敗時保留 transcript.txt、寫入 last_error、維持 AWAITING_DRAFT，且後續補送草稿後清除 last_error。"""
    store = phase31_app.case_store
    cid = _prepare_finalized_cycle(store, cmd_suffix="7", stop_before_finalize=True)

    def _llm_down(transcript: str):
        return {"status": "error", "error": "LLM 連線逾時", "soap": {}}

    res = run_cycle_auto_pipeline(store, cid, transcriber=_fake_asr_ok("完整問診逐字稿"), soap_generator=_llm_down)
    assert res["status"] == "error"
    assert res["error_code"] == "LLM_ERROR"

    cycle = get_cycle(store, cid)
    assert cycle["state"] == STATE_AWAITING_DRAFT
    assert cycle["draft_id"] is None
    assert "LLM_ERROR" in (cycle["last_error"] or "")
    assert (cycle_dir(cid) / "transcript.txt").read_text(encoding="utf-8") == "完整問診逐字稿"

    # 後續成功補送草稿會清除 last_error
    updated, _, _ = submit_cycle_draft(
        store,
        cycle_id=cid,
        payload={"session_id": "manual_retry_1", "soap": SOAP_OK, "transcript": "完整問診逐字稿"},
        actor="manual",
    )
    assert updated["state"] == STATE_AWAITING_CONFIRM
    assert updated["last_error"] is None


def test_run_pipeline_skips_when_draft_already_submitted_or_abandoned(phase31_app):  # noqa: F811
    """若循環已存在草稿或已放棄，背景管線優雅跳過、絕不覆蓋。"""
    store = phase31_app.case_store
    cid_manual = _prepare_finalized_cycle(store, cmd_suffix="8", stop_before_finalize=True)
    submit_cycle_draft(
        store,
        cycle_id=cid_manual,
        payload={"session_id": "soapvoice_first", "soap": SOAP_OK, "transcript": "手動送出"},
        actor="soapvoice",
    )
    called = {"asr": False}

    def _should_not_run(audio_path, *, diarize=False):
        called["asr"] = True
        return _fake_asr_ok()(audio_path, diarize=diarize)

    r1 = run_cycle_auto_pipeline(store, cid_manual, transcriber=_should_not_run, soap_generator=_fake_soap_ok())
    assert r1["status"] == "skipped"
    assert r1["reason"] == "draft_exists"
    assert called["asr"] is False

    cid_ab = _prepare_finalized_cycle(store, cmd_suffix="9", stop_before_finalize=True)
    transition_cycle(store, cid_ab, STATE_ABANDONED, actor="user", reason_code="cancel")
    r2 = run_cycle_auto_pipeline(store, cid_ab, transcriber=_should_not_run, soap_generator=_fake_soap_ok())
    assert r2["status"] == "skipped"
    assert r2["reason"] == "ineligible_state"
    assert called["asr"] is False


def test_schedule_prevents_duplicate_inflight(phase31_app):  # noqa: F811
    """相同 cycle_id 在背景執行中再次排程回傳 False，完成後可再排程。"""
    store = phase31_app.case_store
    cid = _prepare_finalized_cycle(store, cmd_suffix="10", stop_before_finalize=True)
    started = threading.Event()
    release = threading.Event()
    runs = []

    def _slow_runner(s, c_id):
        runs.append(c_id)
        started.set()
        release.wait(timeout=3.0)

    assert schedule_cycle_auto_pipeline(store, cid, runner=_slow_runner) is True
    assert started.wait(timeout=2.0)
    assert schedule_cycle_auto_pipeline(store, cid, runner=_slow_runner) is False
    release.set()

    # 等待背景執行緒結束釋放 inflight 鎖
    for _ in range(50):
        if schedule_cycle_auto_pipeline(store, cid, runner=lambda s, c: None):
            break
        time.sleep(0.02)
    assert len(runs) == 1


def test_api_finalize_triggers_auto_pipeline_and_respects_flags(phase31_client, phase31_app, caplog):  # noqa: F811
    """POST /api/cycles/<id>/finalize 依設定觸發背景管線、支援 auto_generate=false，且日誌零 PHI。"""
    store = phase31_app.case_store
    headers = {"X-API-Key": "valid-key-123"}

    # 1. TESTING=True 預設不自動排程
    assert is_auto_pipeline_enabled(app_config=phase31_app.config) is False

    # 2. 開啟 ELC_CYCLE_AUTO_PIPELINE 並注入測試 runner 驗證端到端流轉
    done = threading.Event()
    secret_transcript = "SECRET-PHI-TRANSCRIPT-PATIENT-LIN-0912345678"
    secret_soap = dict(SOAP_OK)
    secret_soap["s"] = f"Patient reports {secret_transcript} and persistent sore throat for three days."

    def _injected_runner(s, c_id):
        try:
            run_cycle_auto_pipeline(
                s,
                c_id,
                transcriber=_fake_asr_ok(secret_transcript),
                soap_generator=_fake_soap_ok(secret_soap),
            )
        finally:
            done.set()

    phase31_app.config["ELC_CYCLE_AUTO_PIPELINE"] = True
    phase31_app.config["ELC_CYCLE_PIPELINE_RUNNER"] = _injected_runner

    cycle, _ = create_cycle(store, command_id="cmd" + "a" * 29, machine_id="m_api_1")
    cid = cycle["cycle_id"]
    transition_cycle(store, cid, STATE_AWAITING_DRAFT, actor="test")
    chunk = make_wav_chunk(seconds=0.2, seed=81)
    store_chunk(store, cycle_id=cid, seq=0, declared_sha256=wav_sha256(chunk), data=chunk)

    resp = phase31_client.post(
        f"/api/cycles/{cid}/finalize",
        headers=headers,
        json={"total_chunks": 1, "audio_sha256": pcm_sha256([chunk])},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["upload_complete"] is True
    assert body["pipeline_scheduled"] is True

    assert done.wait(timeout=5.0)
    final_cycle = get_cycle(store, cid)
    assert final_cycle["state"] == STATE_AWAITING_CONFIRM
    assert final_cycle["draft_id"]

    # PHI-safe 驗證
    for rec in caplog.records:
        assert secret_transcript not in rec.getMessage()

    # 3. auto_generate=false 顯式關閉排程
    cycle2, _ = create_cycle(store, command_id="cmd" + "b" * 29, machine_id="m_api_2")
    cid2 = cycle2["cycle_id"]
    chunk2 = make_wav_chunk(seconds=0.2, seed=82)
    store_chunk(store, cycle_id=cid2, seq=0, declared_sha256=wav_sha256(chunk2), data=chunk2)

    resp2 = phase31_client.post(
        f"/api/cycles/{cid2}/finalize",
        headers=headers,
        json={"total_chunks": 1, "audio_sha256": pcm_sha256([chunk2]), "auto_generate": False},
    )
    assert resp2.status_code == 200
    assert resp2.get_json()["pipeline_scheduled"] is False
    assert get_cycle(store, cid2)["draft_id"] is None

    # 4. 非法 auto_generate 型別在 finalize 之前即拒收（422 且不改變循環狀態、不產生 full.wav）
    cycle3, _ = create_cycle(store, command_id="cmd" + "c" * 29, machine_id="m_api_3")
    cid3 = cycle3["cycle_id"]
    chunk3 = make_wav_chunk(seconds=0.2, seed=83)
    store_chunk(store, cycle_id=cid3, seq=0, declared_sha256=wav_sha256(chunk3), data=chunk3)

    resp3 = phase31_client.post(
        f"/api/cycles/{cid3}/finalize",
        headers=headers,
        json={"total_chunks": 1, "audio_sha256": pcm_sha256([chunk3]), "auto_generate": "yes"},
    )
    assert resp3.status_code == 422
    c3_after = get_cycle(store, cid3)
    assert c3_after["upload_complete"] is False
    assert c3_after["draft_id"] is None
    assert not (cycle_dir(cid3) / "full.wav").exists()


def test_transcript_repetition_ratio_exact_formula():
    """驗證 _transcript_repetition_ratio(window=8) 確切滑動視窗公式。"""
    assert _transcript_repetition_ratio("") == 0.0
    assert _transcript_repetition_ratio("太短七個字") == 0.0
    assert _transcript_repetition_ratio("甲乙丙丁戊己庚辛壬癸子丑寅卯") == 0.0
    assert _transcript_repetition_ratio("a" * 20) == 0.9231


def test_low_density_whisper_fallback_guards_and_adoption(phase31_app, monkeypatch, caplog):  # noqa: F811
    """測試選配低密度 Whisper 備援：預設關閉、啟用後 ≥1.25× 且低重複率採用、高重複率拒收、缺套件優雅保底。"""
    store = phase31_app.case_store

    sparse_primary = TranscriptionResult(
        transcript="醫師問診簡單幾句話而已。",
        model="sherpa-onnx-sensevoice-int8",
        duration_s=120.0,  # 2 分鐘僅 ~11 字 -> ~5.5 cpm < 60
        elapsed_s=1.0,
        segment_count=1,
    )
    rich_whisper = TranscriptionResult(
        transcript="醫師：今天右膝疼痛多久了？病人：上下樓梯卡卡的已經三週，早上起來特別僵硬，之前貼藥布沒改善。",
        model="faster-whisper-large-v3-turbo",
        duration_s=120.0,
        elapsed_s=8.0,
        segment_count=4,
    )
    looping_whisper = TranscriptionResult(
        transcript="這個藥要飯後吃這個藥要飯後吃這個藥要飯後吃這個藥要飯後吃這個藥要飯後吃這個藥要飯後吃",
        model="faster-whisper-large-v3-turbo",
        duration_s=120.0,
        elapsed_s=8.0,
        segment_count=6,
    )

    # 1. 預設關閉（ELC_ASR_LOW_DENSITY_WHISPER_FALLBACK=0）→ 不呼叫 fallback
    monkeypatch.setenv("ELC_ASR_LOW_DENSITY_WHISPER_FALLBACK", "0")
    fb_called = {"n": 0}

    def _count_fb(p):
        fb_called["n"] += 1
        return rich_whisper

    cid1 = _prepare_finalized_cycle(store, cmd_suffix="21", stop_before_finalize=True)
    r1 = run_cycle_auto_pipeline(
        store,
        cid1,
        transcriber=lambda p, *, diarize=False: sparse_primary,
        fallback_transcriber=_count_fb,
        soap_generator=_fake_soap_ok(),
    )
    assert r1["status"] == "completed"
    assert r1["asr_model"] == "sherpa-onnx-sensevoice-int8"
    assert fb_called["n"] == 0

    # 2. 開啟後滿足 ≥1.25× 且重複率 < 0.15 → 採用 Whisper 備援
    monkeypatch.setenv("ELC_ASR_LOW_DENSITY_WHISPER_FALLBACK", "1")
    cid2 = _prepare_finalized_cycle(store, cmd_suffix="22", stop_before_finalize=True)
    r2 = run_cycle_auto_pipeline(
        store,
        cid2,
        transcriber=lambda p, *, diarize=False: sparse_primary,
        fallback_transcriber=lambda p: rich_whisper,
        soap_generator=_fake_soap_ok(),
    )
    assert r2["status"] == "completed"
    assert r2["asr_model"] == "faster-whisper-large-v3-turbo"
    assert "上下樓梯" in cycle_draft_view(store, cid2, include_transcript=True)["transcript"]

    # 3. Whisper 結果高重複迴圈 → 護欄拒收、保留原 Sherpa 逐字稿
    cid3 = _prepare_finalized_cycle(store, cmd_suffix="23", stop_before_finalize=True)
    r3 = run_cycle_auto_pipeline(
        store,
        cid3,
        transcriber=lambda p, *, diarize=False: sparse_primary,
        fallback_transcriber=lambda p: looping_whisper,
        soap_generator=_fake_soap_ok(),
    )
    assert r3["status"] == "completed"
    assert r3["asr_model"] == "sherpa-onnx-sensevoice-int8"
    assert cycle_draft_view(store, cid3, include_transcript=True)["transcript"] == sparse_primary.transcript

    # 4. Whisper 缺套件（ASRUnavailableError）→ 優雅保底原 Sherpa 逐字稿，不中斷管線
    cid4 = _prepare_finalized_cycle(store, cmd_suffix="24", stop_before_finalize=True)

    def _no_whisper(p):
        raise ASRUnavailableError("faster-whisper not installed")

    r4 = run_cycle_auto_pipeline(
        store,
        cid4,
        transcriber=lambda p, *, diarize=False: sparse_primary,
        fallback_transcriber=_no_whisper,
        soap_generator=_fake_soap_ok(),
    )
    assert r4["status"] == "completed"
    assert r4["asr_model"] == "sherpa-onnx-sensevoice-int8"

    # PHI-safe 確認：日誌絕不含逐字稿原文
    for rec in caplog.records:
        assert "上下樓梯" not in rec.getMessage()
        assert "這個藥要飯後吃" not in rec.getMessage()
