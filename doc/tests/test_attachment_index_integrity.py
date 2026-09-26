"""A-CR-10：附件索引不得因並行寫入遺失紀錄，損毀時必須報錯而非當成沒有附件。"""
import io
import os
import threading

import pytest
from PIL import Image

from elc_audit_engine import attachment_store
from elc_audit_engine.attachment_store import AttachmentIndexCorruptError


@pytest.fixture(autouse=True)
def att_dir(tmp_path, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ATTACHMENTS_DIR", str(tmp_path))
    return tmp_path


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buf, format="PNG")
    return buf.getvalue()


def test_concurrent_uploads_keep_every_record():
    png = _png()
    threads = [
        threading.Thread(target=attachment_store.save_attachment, args=("APP-1", png, f"{i}.png"))
        for i in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(attachment_store.list_attachments("APP-1")) == 20


def test_corrupt_index_raises_instead_of_resetting(att_dir):
    attachment_store.save_attachment("APP-1", _png(), "a.png")
    (att_dir / "APP-1" / "meta.json").write_text("[{broken", encoding="utf-8")
    with pytest.raises(AttachmentIndexCorruptError):
        attachment_store.list_attachments("APP-1")
    with pytest.raises(AttachmentIndexCorruptError):
        attachment_store.save_attachment("APP-1", _png(), "b.png")
    with pytest.raises(AttachmentIndexCorruptError):
        attachment_store.has_attachment("APP-1")
    # 損毀的索引維持原狀，未被覆寫成單筆
    assert (att_dir / "APP-1" / "meta.json").read_text(encoding="utf-8") == "[{broken"


def test_delete_updates_index_and_removes_file(att_dir):
    rec = attachment_store.save_attachment("APP-1", _png(), "a.png")
    assert attachment_store.delete_attachment("APP-1", rec.id) is True
    assert attachment_store.list_attachments("APP-1") == []
    assert not os.path.exists(rec.file_path)
    assert not [p for p in os.listdir(att_dir / "APP-1") if p.endswith(".tmp")]


def test_extra_keys_in_index_do_not_crash(att_dir):
    import json

    rec = attachment_store.save_attachment("APP-1", _png(), "a.png")
    meta = att_dir / "APP-1" / "meta.json"
    data = json.loads(meta.read_text(encoding="utf-8"))
    data[0]["future_field"] = "x"
    meta.write_text(json.dumps(data), encoding="utf-8")
    assert [r.id for r in attachment_store.list_attachments("APP-1")] == [rec.id]
