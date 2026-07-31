"""doc_converter.convert_doc_files 驗收測試（Plan 02-03 Task 1）。"""

import shutil
import subprocess

import docx
import pytest

from config.settings import RULE_SOURCE_DIR
from elc_audit_engine.rule_repository.docx_tree import doc_converter


def _soffice_is_functional() -> bool:
    """實際探測 soffice 是否能執行，不只是檢查 PATH 上有沒有這個檔案。

    某些沙箱/容器環境裡 soffice 存在於 PATH 但因 profile/dconf 權限問題
    執行時會直接失敗（非 0 結束碼），單用 shutil.which 判斷會誤判環境健康。
    """
    if shutil.which("soffice") is None:
        return False
    try:
        result = subprocess.run(["soffice", "--version"], capture_output=True, timeout=15)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


requires_soffice = pytest.mark.skipif(
    not _soffice_is_functional(),
    reason="soffice (LibreOffice) not available/functional — .doc conversion tests need it",
)


@requires_soffice
def test_convert_doc_files_converts_all_legacy_doc_files(tmp_path):
    staging_dir = str(tmp_path / "staging")
    converted = doc_converter.convert_doc_files(RULE_SOURCE_DIR, staging_dir)

    assert len(converted) == 11

    for path in converted:
        # 驗證輸出為有效的 OOXML，而非毀損檔案
        document = docx.Document(path)
        assert document is not None


def test_convert_doc_files_raises_runtime_error_when_soffice_missing(tmp_path, monkeypatch):
    staging_dir = str(tmp_path / "staging")

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("soffice not found")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="soffice"):
        doc_converter.convert_doc_files(RULE_SOURCE_DIR, staging_dir)
