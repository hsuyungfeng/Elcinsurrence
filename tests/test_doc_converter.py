"""convert_doc_files 驗收測試（Plan 02-03 Task 1）。"""

import subprocess

import docx
import pytest

from config.settings import RULE_SOURCE_DIR
from elc_audit_engine.rule_repository.docx_tree.doc_converter import (
    convert_doc_files,
    soffice_is_functional,
)




requires_soffice = pytest.mark.skipif(
    not soffice_is_functional(),
    reason="soffice headless conversion unavailable (real-conversion probe failed) — .doc conversion tests need it",
)


@requires_soffice
def test_convert_doc_files_converts_all_legacy_doc_files(tmp_path):
    staging_dir = str(tmp_path / "staging")
    converted = convert_doc_files(RULE_SOURCE_DIR, staging_dir)

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
        convert_doc_files(RULE_SOURCE_DIR, staging_dir)
