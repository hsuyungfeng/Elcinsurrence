"""佐證庫（Phase 17-01）：vault_key 校驗、自動分類、ZIP 解壓、路徑穿越防護與 API。"""

from __future__ import annotations

import io
import os
import zipfile

import pytest

from config import settings
from elc_audit_engine import evidence_vault as ev

KEY = {"X-API-Key": "valid-key-123"}
VALID_KEY = "A123625499-2605"


@pytest.fixture
def vault_dir(tmp_path, monkeypatch):
    """把 DATA_DIR 指向暫存目錄，佐證庫寫入 tmp_path/evidence_vault，不污染正式資料。"""
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    return tmp_path / "evidence_vault"


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


# --- vault_key 校驗 -----------------------------------------------------


@pytest.mark.parametrize("key", [VALID_KEY, "B100000001-0101", "Z999999999-9912"])
def test_valid_vault_key_accepted(key):
    assert ev.validate_vault_key(key) == key


@pytest.mark.parametrize(
    "key",
    [
        "a123625499-2605",  # 小寫身分證首字母
        "A12362549-2605",  # 九碼
        "A1236254991-2605",  # 十一碼
        "A123625499-260",  # 年月不足四碼
        "A123625499-26055",
        "1123625499-2605",  # 首字母非英文
        "A123625499_2605",
        "../A123625499-2605",  # 路徑穿越
        "A123625499-2605/../../x",
        "A123625499-2605\n",  # fullmatch 必須擋掉結尾換行
        "",
        None,
    ],
)
def test_invalid_vault_key_rejected(key):
    with pytest.raises(ev.InvalidVaultKeyError):
        ev.validate_vault_key(key)


# --- 單檔上傳與自動分類 -------------------------------------------------


@pytest.mark.parametrize(
    ("filename", "category"),
    [
        ("xray.jpg", "images"),
        ("scan.JPEG", "images"),  # 副檔名大小寫不敏感
        ("ct.dicom", "images"),
        ("photo.heic", "images"),
        ("visit.mp3", "audio"),
        ("dictation.m4a", "audio"),
        ("rec.wav", "audio"),
        ("rec.aac", "audio"),
        ("report.pdf", "reports"),
        ("lab.csv", "reports"),
        ("note.txt", "reports"),  # .txt 同時屬 reports 與 records，依順序歸入 reports
        ("meta.json", "records"),
    ],
)
def test_single_file_auto_classified(vault_dir, filename, category):
    vf = ev.store_single_file(VALID_KEY, filename, b"payload")
    assert vf.category == category
    assert vf.filename == filename
    assert os.path.isfile(os.path.join(vault_dir, VALID_KEY, category, filename))
    assert vf.size == len(b"payload")


@pytest.mark.parametrize("filename", ["malware.exe", "noext", "script.sh", "doc.docx"])
def test_unsupported_extension_rejected(vault_dir, filename):
    with pytest.raises(ev.UnsupportedFileError):
        ev.store_single_file(VALID_KEY, filename, b"x")
    assert not vault_dir.exists() or not any(vault_dir.rglob("*.*"))


def test_duplicate_filename_gets_suffix_instead_of_overwrite(vault_dir):
    first = ev.store_single_file(VALID_KEY, "xray.png", b"first")
    second = ev.store_single_file(VALID_KEY, "xray.png", b"second")
    assert first.filename == "xray.png"
    assert second.filename == "xray_1.png"
    with open(first.path, "rb") as f:
        assert f.read() == b"first"


# --- ZIP 解壓與分類 -----------------------------------------------------


def test_zip_members_auto_classified_and_flattened(vault_dir):
    data = _zip_bytes({
        "photos/xray.png": b"png",
        "audio/visit.mp3": b"mp3",
        "reports/lab.pdf": b"pdf",
        "meta.json": b"{}",
    })
    saved = ev.store_zip(VALID_KEY, data)
    got = {(f.category, f.filename) for f in saved}
    assert got == {
        ("images", "xray.png"),
        ("audio", "visit.mp3"),
        ("reports", "lab.pdf"),
        ("records", "meta.json"),
    }
    assert os.path.isfile(os.path.join(vault_dir, VALID_KEY, "images", "xray.png"))


def test_zip_with_unsupported_member_rejected_and_rolled_back(vault_dir):
    data = _zip_bytes({"ok.png": b"png", "bad.exe": b"exe"})
    with pytest.raises(ev.UnsupportedFileError):
        ev.store_zip(VALID_KEY, data)
    # 整包拒收：先前已寫入的 ok.png 必須被清除
    assert not os.path.exists(os.path.join(vault_dir, VALID_KEY, "images", "ok.png"))


def test_corrupt_zip_rejected(vault_dir):
    with pytest.raises(ev.VaultError):
        ev.store_zip(VALID_KEY, b"this is not a zip")


def test_zip_member_count_limit(vault_dir, monkeypatch):
    monkeypatch.setattr(ev, "MAX_ZIP_MEMBERS", 2)
    data = _zip_bytes({f"f{i}.txt": b"x" for i in range(3)})
    with pytest.raises(ev.VaultError, match="檔案數超過上限"):
        ev.store_zip(VALID_KEY, data)


def test_zip_bomb_member_size_limit_rolls_back(vault_dir, monkeypatch):
    monkeypatch.setattr(ev, "MAX_MEMBER_BYTES", 10)
    data = _zip_bytes({"ok.png": b"png", "big.txt": b"x" * 100})
    with pytest.raises(ev.VaultError, match="單檔上限"):
        ev.store_zip(VALID_KEY, data)
    assert not os.path.exists(os.path.join(vault_dir, VALID_KEY, "images", "ok.png"))
    assert not os.path.exists(os.path.join(vault_dir, VALID_KEY, "reports", "big.txt"))


# --- 路徑穿越防護 -------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    ["../evil.png", "..", ".", "sub/evil.png", "sub\\evil.png", "C:evil.png", "a\x00b.png", " lead.png", ""],
)
def test_single_file_traversal_filename_rejected(vault_dir, filename):
    with pytest.raises(ev.UnsupportedFileError):
        ev.store_single_file(VALID_KEY, filename, b"x")
    assert not vault_dir.exists() or not any(p.is_file() for p in vault_dir.rglob("*"))


def test_zip_member_with_parent_segment_rejected(vault_dir):
    data = _zip_bytes({"../../escape.png": b"png"})
    with pytest.raises(ev.UnsupportedFileError):
        ev.store_zip(VALID_KEY, data)
    assert not vault_dir.exists() or not any(vault_dir.rglob("escape.png"))


def test_zip_member_absolute_path_rejected(vault_dir):
    # 絕對路徑成員屬於穿越嘗試，整包拒收（不靜默改寫為 basename）
    with pytest.raises(ev.UnsupportedFileError):
        ev.store_zip(VALID_KEY, _zip_bytes({"/etc/passwd.txt": b"x"}))
    assert not vault_dir.exists() or not any(vault_dir.rglob("passwd.txt"))


def test_zip_member_nested_dir_flattened_into_category(vault_dir):
    # 相對目錄成分（非穿越）攤平為 basename，仍落在 vault_key 目錄內
    saved = ev.store_zip(VALID_KEY, _zip_bytes({"a/b/c/xray.png": b"png"}))
    assert saved[0].filename == "xray.png"
    assert saved[0].path.startswith(str(vault_dir / VALID_KEY))


def test_get_vault_file_rejects_traversal_category_and_filename(vault_dir):
    ev.store_single_file(VALID_KEY, "xray.png", b"png")
    with pytest.raises(ev.UnsupportedFileError):
        ev.get_vault_file(VALID_KEY, "../images", "xray.png")
    with pytest.raises(ev.UnsupportedFileError):
        ev.get_vault_file(VALID_KEY, "images", "../xray.png")
    with pytest.raises(ev.UnsupportedFileError):
        ev.get_vault_file(VALID_KEY, "images", "..")
    with pytest.raises(ev.InvalidVaultKeyError):
        ev.get_vault_file("../" + VALID_KEY, "images", "xray.png")


def test_get_vault_file_blocks_symlink_escape(vault_dir, tmp_path):
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("SECRET", encoding="utf-8")
    cat_dir = vault_dir / VALID_KEY / "reports"
    cat_dir.mkdir(parents=True)
    os.symlink(outside, cat_dir / "link.txt")
    with pytest.raises(ev.UnsupportedFileError):
        ev.get_vault_file(VALID_KEY, "reports", "link.txt")


def test_get_vault_file_missing_raises_not_found(vault_dir):
    with pytest.raises(FileNotFoundError):
        ev.get_vault_file(VALID_KEY, "images", "nope.png")


# --- 列表 -----------------------------------------------------------------


def test_list_vault_files_groups_by_category(vault_dir):
    ev.store_single_file(VALID_KEY, "a.png", b"1")
    ev.store_single_file(VALID_KEY, "b.mp3", b"22")
    grouped = ev.list_vault_files(VALID_KEY)
    assert set(grouped) == {"images", "audio", "reports", "records"}
    assert [f.filename for f in grouped["images"]] == ["a.png"]
    assert [f.filename for f in grouped["audio"]] == ["b.mp3"]
    assert grouped["records"] == []


def test_list_vault_files_empty_key_returns_empty_categories(vault_dir):
    grouped = ev.list_vault_files("B100000001-0101")
    assert all(files == [] for files in grouped.values())


# --- API ----------------------------------------------------------------


@pytest.fixture
def client(make_api_app):
    app = make_api_app()
    with app.test_client() as c:
        yield c


def test_api_requires_authentication(client, vault_dir):
    assert client.get(f"/api/vault/{VALID_KEY}").status_code == 401


def test_api_get_empty_vault_structure(client, vault_dir):
    res = client.get(f"/api/vault/{VALID_KEY}", headers=KEY)
    assert res.status_code == 200
    body = res.get_json()
    assert body["total"] == 0
    assert set(body["categories"]) == {"images", "audio", "reports", "records"}


def test_api_invalid_key_returns_400(client, vault_dir):
    res = client.get("/api/vault/not-a-key", headers=KEY)
    assert res.status_code == 400
    assert res.get_json()["status"] == "error"


def test_api_upload_single_and_zip_then_list_and_fetch(client, vault_dir):
    res = client.post(
        f"/api/vault/{VALID_KEY}/upload",
        headers=KEY,
        data={
            "file": [
                (io.BytesIO(b"\x89PNG-fake"), "xray.png"),
                (io.BytesIO(_zip_bytes({"visit.mp3": b"mp3-bytes"})), "bundle.zip"),
            ]
        },
        content_type="multipart/form-data",
    )
    assert res.status_code == 200, res.get_json()
    saved = {(f["category"], f["filename"]) for f in res.get_json()["saved"]}
    assert saved == {("images", "xray.png"), ("audio", "visit.mp3")}

    listing = client.get(f"/api/vault/{VALID_KEY}", headers=KEY).get_json()
    assert listing["total"] == 2
    assert listing["categories"]["audio"]["count"] == 1

    fetched = client.get(f"/api/vault/{VALID_KEY}/files/audio/visit.mp3", headers=KEY)
    assert fetched.status_code == 200
    assert fetched.data == b"mp3-bytes"


def test_api_upload_without_file_returns_400(client, vault_dir):
    res = client.post(f"/api/vault/{VALID_KEY}/upload", headers=KEY, data={},
                      content_type="multipart/form-data")
    assert res.status_code == 400


def test_api_upload_unsupported_returns_400(client, vault_dir):
    res = client.post(
        f"/api/vault/{VALID_KEY}/upload",
        headers=KEY,
        data={"file": (io.BytesIO(b"MZ"), "virus.exe")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 400


def test_api_upload_invalid_key_returns_400(client, vault_dir):
    res = client.post(
        "/api/vault/..%2Fetc/upload",
        headers=KEY,
        data={"file": (io.BytesIO(b"x"), "a.txt")},
        content_type="multipart/form-data",
    )
    assert res.status_code in (400, 404)
    assert res.status_code != 200


def test_api_file_route_blocks_traversal(client, vault_dir):
    ev.store_single_file(VALID_KEY, "xray.png", b"png")
    for path in (
        f"/api/vault/{VALID_KEY}/files/images/..%2F..%2Fsecret.txt",
        f"/api/vault/{VALID_KEY}/files/..%2Fimages/xray.png",
        f"/api/vault/{VALID_KEY}/files/images/..",
    ):
        res = client.get(path, headers=KEY)
        assert res.status_code in (400, 404), path


def test_api_file_missing_returns_404(client, vault_dir):
    res = client.get(f"/api/vault/{VALID_KEY}/files/images/none.png", headers=KEY)
    assert res.status_code == 404
