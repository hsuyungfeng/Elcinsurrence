"""Info 第一組：安全與 PHI（B-IN-01/02/09/13）。"""
import pytest

from elc_audit_engine.parsers.submission_xml import (
    SubmissionXmlError,
    _neutralize_declaration,
    parse_submission_xml_bytes,
)
from elc_audit_engine.rule_repository.mapping import llm_client

_XXE = b"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>
<outpatient><tdata><t1>&x;</t1></tdata></outpatient>"""

_BOMB = b"""<?xml version="1.0"?>
<!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>
<outpatient><tdata><t1>&b;</t1></tdata></outpatient>"""


@pytest.mark.parametrize("raw", [_XXE, _BOMB])
def test_dtd_and_entities_rejected(raw):
    with pytest.raises(SubmissionXmlError):
        parse_submission_xml_bytes(raw)


def test_declaration_regex_does_not_touch_stylesheet_pi():
    text = '<?xml-stylesheet href="a.xsl"?><outpatient/>'
    assert _neutralize_declaration(text) == text


@pytest.mark.parametrize("url", ["http://localhost:8080", "http://127.0.0.1:8080",
                                 "http://192.168.1.20:8080", "http://[::1]:8080"])
def test_local_llm_urls_allowed(url):
    llm_client.assert_local_llm_url(url)


@pytest.mark.parametrize("url", ["http://8.8.8.8", "https://api.example.com"])
def test_remote_llm_urls_refused(url, monkeypatch):
    monkeypatch.delenv("ELC_ALLOW_REMOTE_LLM", raising=False)
    with pytest.raises(llm_client.RemoteLLMRefusedError):
        llm_client.assert_local_llm_url(url)


def test_remote_llm_explicit_override(monkeypatch):
    monkeypatch.setenv("ELC_ALLOW_REMOTE_LLM", "1")
    llm_client.assert_local_llm_url("https://llm.clinic.example")


def test_data_subdirs_follow_data_dir(monkeypatch, tmp_path):
    import importlib

    import config.settings as settings

    for k in ("DB_DIR", "RAG_DIR", "OUTPUT_DIR", "AUDIT_LOG_PATH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    try:
        reloaded = importlib.reload(settings)
        assert reloaded.DB_DIR == str(tmp_path / "db")
        assert reloaded.OUTPUT_DIR == str(tmp_path / "output")
    finally:
        monkeypatch.delenv("DATA_DIR")
        importlib.reload(settings)
