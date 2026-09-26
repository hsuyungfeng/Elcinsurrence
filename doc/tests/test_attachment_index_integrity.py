"""附件索引（第 5 步：SQLite）：併發不遺失、舊 meta.json 遷移、損毀不當成沒有附件。"""
import io
import json
import os
import shutil
import threading

import pytest
from PIL import Image

from elc_audit_engine import attachment_store
from elc_audit_engine.attachment_store import AttachmentIndexCorruptError


@pytest.fixture(autouse=True)
def att_dir(tmp_path, monkeypatch):
    from config import settings

    d = tmp_path / "att"
    monkeypatch.setattr(settings, "ATTACHMENTS_DIR", str(d))
    return d


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buf, format="PNG")
    return buf.getvalue()


def test_concurrent_uploads_keep_every_record():
    png = _png()
    errors = []

    def worker(i):
        try:
            attachment_store.save_attachment("APP-1", png, f"{i}.png")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(attachment_store.list_attachments("APP-1")) == 20


def _legacy_case(att_dir, meta):
    case_dir = att_dir / "APP-L"
    case_dir.mkdir(parents=True)
    (case_dir / "2026-01-01_abc.png").write_bytes(_png())
    (case_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return case_dir


def test_legacy_meta_json_is_migrated_once(att_dir):
    case_dir = _legacy_case(att_dir, [{
        "id": "abc", "case_seq": "APP-L", "order_seq": None, "order_code": "X",
        "filename": "2026-01-01_abc.png", "file_path": "/old/abs/path.png",
        "file_size": 10, "mime_type": "image/png", "created_at": "2026-01-01T00:00:00",
        "future_field": "ignored",
    }])
    recs = attachment_store.list_attachments("APP-L")
    assert [r.id for r in recs] == ["abc"]
    assert recs[0].file_path == str(case_dir / "2026-01-01_abc.png")  # 不沿用舊絕對路徑
    assert not (case_dir / "meta.json").exists()
    assert (case_dir / "meta.json.migrated").exists()
    assert [r.id for r in attachment_store.list_attachments("APP-L")] == ["abc"]


def test_corrupt_legacy_meta_raises_and_is_left_untouched(att_dir):
    case_dir = att_dir / "APP-C"
    case_dir.mkdir(parents=True)
    (case_dir / "meta.json").write_text("[{broken", encoding="utf-8")
    with pytest.raises(AttachmentIndexCorruptError):
        attachment_store.list_attachments("APP-C")
    with pytest.raises(AttachmentIndexCorruptError):
        attachment_store.has_attachment("APP-C")
    with pytest.raises(AttachmentIndexCorruptError):
        attachment_store.save_attachment("APP-C", _png(), "b.png")
    assert (case_dir / "meta.json").read_text(encoding="utf-8") == "[{broken"
    assert [p for p in os.listdir(case_dir) if p != "meta.json"] == []  # 失敗的上傳不留孤兒檔


def test_delete_updates_index_and_removes_file():
    rec = attachment_store.save_attachment("APP-1", _png(), "a.png")
    assert attachment_store.delete_attachment("APP-1", rec.id) is True
    assert attachment_store.list_attachments("APP-1") == []
    assert not os.path.exists(rec.file_path)
    assert attachment_store.delete_attachment("APP-1", rec.id) is False


def test_index_survives_relocating_attachments_dir(att_dir, tmp_path, monkeypatch):
    from config import settings

    rec = attachment_store.save_attachment("APP-1", _png(), "a.png", order_seq="2")
    moved = tmp_path / "moved"
    shutil.move(str(att_dir), str(moved))
    monkeypatch.setattr(settings, "ATTACHMENTS_DIR", str(moved))
    recs = attachment_store.list_attachments("APP-1", "2")
    assert [r.id for r in recs] == [rec.id]
    assert recs[0].file_path.startswith(str(moved))
