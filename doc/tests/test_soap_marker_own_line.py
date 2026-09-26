"""B-CR-01：SOAP 標記獨佔一行時，後續內文必須歸入該段。"""
from elc_audit_engine.parsers.soap import parse_soap_text


def test_marker_on_own_line_collects_following_lines():
    doc = parse_soap_text("S:\n頭痛三天\n夜間加劇\nO:\nBP 120/80\nA:\n高血壓\nP:\n回診")
    assert doc.sections == {
        "S": ("頭痛三天\n夜間加劇",),
        "O": ("BP 120/80",),
        "A": ("高血壓",),
        "P": ("回診",),
    }
    assert doc.unclassified == ()
    assert doc.confidence == "high"


def test_empty_marker_produces_no_segment():
    doc = parse_soap_text("S:\nO: BP 120/80")
    assert doc.sections == {"O": ("BP 120/80",)}


def test_only_empty_markers_is_not_high_confidence():
    doc = parse_soap_text("S:\nO:\n")
    assert doc.sections == {}
    assert doc.confidence == "low"
