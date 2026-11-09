import pytest
from elc_audit_engine.comparator.soap_comparison import (
    compare_soap_with_template,
    extract_icd10_codes,
)


def test_extract_icd10_codes():
    text = "Diagnosis: Acute pulpitis (K04.0), secondary dental caries K02.9 and J00."
    icds = extract_icd10_codes(text)
    assert "K04.0" in icds
    assert "K02.9" in icds
    assert "J00" in icds


def test_compare_soap_with_template_identical():
    soap = {
        "s": "Severe tooth pain on lower right quadrant for 3 days.",
        "o": "Tooth 46 cold test positive, percussion tender.",
        "a": "K04.0 Irreversible pulpitis tooth 46.",
        "p": "Pulpectomy and canal debridement under local anesthesia.",
    }
    res = compare_soap_with_template(soap, soap, rule_text="符合 K04.0 給付規定")
    assert res["advisory_only"] is True
    assert res["overall_similarity"] == 1.0
    assert res["section_similarities"]["s"] == 1.0
    assert res["missing_sections"] == []
    assert res["icd10_comparison"]["consistent_with_template"] is True
    assert res["icd10_comparison"]["consistent_with_rule"] is True


def test_compare_soap_with_template_differences():
    draft = {
        "s": "Patient complained of mild tooth discomfort when chewing.",
        "o": "Deep caries on tooth 46.",
        "a": "K04.0 Pulpitis.",
        "p": "Composite resin restoration.",
    }
    template = {
        "s": "Severe spontaneous throbbing pain on tooth 46.",
        "o": "Electric pulp test negative, percussion positive on 46.",
        "a": "K04.0 Irreversible pulpitis, necrotic pulp.",
        "p": "Root canal therapy initiated.",
    }
    res = compare_soap_with_template(draft, template, rule_text="K04.0, K04.1")
    assert res["advisory_only"] is True
    assert 0.0 < res["overall_similarity"] < 1.0
    assert res["missing_sections"] == []
    assert "K04.0" in res["icd10_comparison"]["matched_icds"]


def test_compare_soap_with_template_missing_sections():
    draft = {
        "s": "Toothache.",
        "o": "",
        "a": "K02.1",
        "p": "",
    }
    template = {
        "s": "Pain.",
        "o": "Finding.",
        "a": "K02.1 Caries.",
        "p": "Fill.",
    }
    res = compare_soap_with_template(draft, template)
    assert "o" in res["missing_sections"]
    assert "p" in res["missing_sections"]
    assert res["section_similarities"]["o"] == 0.0
    assert res["section_similarities"]["p"] == 0.0
