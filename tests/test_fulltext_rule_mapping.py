"""Phase 38：零 LLM 確定性官方完整給付規定條文建置（build_fulltext_mapping）、
sync_latest_rules 自動連動、防洗空策略與全文展開區（payment_text 完整展開、不截斷）測試。

所有測試均於 tmp_path 合成 ODT/DOCX/CSV/SQLite 執行，絕不讀寫正式 data/db/rules.sqlite3。
"""

from __future__ import annotations

import re
import sqlite3
import zipfile
from pathlib import Path

from elc_audit_engine.monthly_audit import (
    BatchAudit,
    CaseAudit,
    OrderFinding,
    STATUS_RESTRICTION,
)
from elc_audit_engine.monthly_report_html import render_batch_report_html
from elc_audit_engine.rule_repository import get_rule
from elc_audit_engine.rule_repository.mapping.build_fulltext_mapping import (
    OFFICIAL_ARTICLE_SOURCE,
    build_fulltext_mapping,
    lookup_odt_chapter,
    parse_odt_drug_chapters,
)
from elc_audit_engine.rule_repository.scripts.sync_latest_rules import (
    REPLACE_CONFIRM_TOKEN,
    rules_status,
    sync_latest_rules,
)
from elc_audit_engine.services.report_renderer import (
    ReviewCaseView,
    RuleBlock,
    render_aggregated_review_html,
)


def _make_synthetic_odt(path: Path) -> Path:
    content_xml = """<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
    xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0">
  <office:body>
    <office:text>
      <text:p>目錄</text:p>
      <text:p>1.2.1. 抗憂鬱劑</text:p>
      <text:p>第1節 神經系統藥物</text:p>
      <text:p>1.2.1.選擇性血清促進素再吸收抑制劑(SSRI)</text:p>
      <text:p>使用時病歷上應詳細註明診斷依據及治療計畫。</text:p>
      <text:p>2.18歲以上非瓣膜性心房纖維顫動病患，須符合條件。</text:p>
      <text:p>1.3.2.6 Carbamazepine（100/8/1）</text:p>
      <text:p>限癲癇及三叉神經痛病患使用，使用前應評估基因風險。</text:p>
      <text:p>第2節 心臟血管及腎臟藥物</text:p>
      <text:p>2.8.2.1.Iloprost：限肺動脈高壓病患事前審查核准後使用。</text:p>
      <text:p>2.8.2.2.Sildenafil：限肺動脈高壓病患使用，需附心導管報告。</text:p>
      <text:p>第7節 腸胃藥物</text:p>
      <text:p>7.1.消化性潰瘍用藥：</text:p>
      <text:p>1.須經上消化道內視鏡檢查或上消化道X光攝影報告證實。</text:p>
      <table:table>
        <table:table-row>
          <table:table-cell><text:p>等級</text:p></table:table-cell>
          <table:table-cell><text:p>最長療程</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>Grade A/B</text:p></table:table-cell>
          <table:table-cell><text:p>4個月</text:p></table:table-cell>
        </table:table-row>
      </table:table>
    </office:text>
  </office:body>
</office:document-content>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("content.xml", content_xml.encode("utf-8"))
    return path


def _make_synthetic_docx_review(path: Path) -> Path:
    doc_xml = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>一、外科審查原則</w:t></w:r></w:p>
    <w:p><w:r><w:t>(十三)脂肪瘤或腱鞘囊腫摘出術之申報原則：</w:t></w:r></w:p>
    <w:p><w:r><w:t>1.脂肪瘤如在皮下以62010C皮下腫瘤摘除術申報。</w:t></w:r></w:p>
    <w:p><w:r><w:t>2.腱鞘囊腫則以64087C項列報。</w:t></w:r></w:p>
    <w:p><w:r><w:t>(十八)頭皮腫瘤於髮線以內按83048C頭皮腫瘤申報。</w:t></w:r></w:p>
  </w:body>
</w:document>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", doc_xml.encode("utf-8"))
    return path


def _make_synthetic_docx_table(path: Path) -> Path:
    doc_xml = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>83048C</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>頭皮腫瘤 Scalp tumor註：1.包括頭皮縫合(suture of scalp)2.一般頭皮縫合依創傷處置申報。</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>4190</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", doc_xml.encode("utf-8"))
    return path


def _write_csv(path: Path, lines: list[str]) -> Path:
    path.write_bytes(("\ufeff" + "\n".join(lines) + "\n").encode("utf-8"))
    return path


def test_parse_odt_chapters_tables_dotless_parent_and_no_age_false_positive(tmp_path):
    """ODT 解析：保留附表、支援無尾點 1.3.2.6、排除 2.18歲 誤判、父章節 2.8.2 彙整全部子節。"""
    odt = _make_synthetic_odt(tmp_path / "完整給付規定1140221.odt")
    chapters = parse_odt_drug_chapters(odt)

    # 1.2.1 應取內文最長段（非目錄短行），且「2.18歲」留在 1.2.1 內文而非誤切為章節 2.18
    assert "2.18" not in chapters
    assert "2.18歲以上" in chapters["1.2.1"]
    assert "詳細註明診斷依據" in chapters["1.2.1"]

    # 無尾點章節 1.3.2.6 正確擷取
    assert "Carbamazepine" in chapters["1.3.2.6"]
    assert "基因風險" in chapters["1.3.2.6"]

    # 附表文字完整保留於 7.1
    assert "Grade A/B | 4個月" in chapters["7.1"]

    # 父章節 2.8.2 自動依序彙整 2.8.2.1 + 2.8.2.2
    parent_txt = lookup_odt_chapter(chapters, "2.8.2.")
    assert parent_txt is not None
    assert "Iloprost" in parent_txt and "Sildenafil" in parent_txt
    assert parent_txt.index("Iloprost") < parent_txt.index("Sildenafil")


def test_build_fulltext_mapping_sync_integration_missing_docs_preserve_and_orphan_prune(tmp_path):
    """整合驗證：ODT+DOCX 跨段落+表格+CSV 備註去重、sync 自動連動、缺官方目錄不洗空、replace 清孤立列。"""
    docs_dir = tmp_path / "official"
    docs_dir.mkdir()
    _make_synthetic_odt(docs_dir / "完整給付規定1140221.odt")
    _make_synthetic_docx_review(docs_dir / "西醫基層醫療費用審查注意事項-外科.docx")
    _make_synthetic_docx_table(docs_dir / "2-2-7第二部第二章第七節手術-113.12.01.docx")

    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    _write_csv(
        rules_dir / "醫療服務給付項目支付標準261119已填支付規定.csv",
        [
            "診療項目代碼,中文項目名稱,備註,支付規定,生效起日,生效迄日",
            '83048C,頭皮腫瘤,"1.包括頭皮縫合(suture of scalp)2.一般頭皮縫合依創傷處置申報。",審查原則：簡要,20231001,29101231',
            '62010C,皮下腫瘤摘除術,單獨官方備註文字,審查原則：簡要,20231001,29101231',
            '99001C,待移除舊碼,舊備註文字,舊規定,20200101,29101231',
        ],
    )
    _write_csv(
        rules_dir / "藥品項查詢項目檔261028AI  摘要支付價大於0.csv",
        [
            "藥品代號,藥品中文名稱,給付規定章節,給付規定,有效起日,有效迄日,支付價,AI-note",
            "AC25230100,胃藥測試,7.1.,截斷300字...,1120101,9991231,6.50,AI",
            "AB10000100,高壓藥測試,2.8.2.,截斷300字...,1120101,9991231,12.00,AI",
        ],
    )

    db_path = str(tmp_path / "rules.sqlite3")
    res = sync_latest_rules(
        db_path=db_path,
        rules_dir=str(rules_dir),
        replace=False,
        official_docs_dir=str(docs_dir),
    )
    assert res.rule_mapping_rows == 5
    status = rules_status(db_path=db_path, rules_dir=str(rules_dir))
    assert status["db"]["rule_mapping_rows"] == 5

    # 1. 62010C 須包含完整 (十三) 跨段落條文（含 1. 與 2. 兩項）＋ CSV 備註
    r_62010 = get_rule("62010C", db_path=db_path)
    assert r_62010.article_source == OFFICIAL_ARTICLE_SOURCE
    assert r_62010.article_full_text is not None
    assert "(十三)脂肪瘤或腱鞘囊腫摘出術之申報原則：" in r_62010.article_full_text
    assert "2.腱鞘囊腫則以64087C項列報。" in r_62010.article_full_text
    assert "單獨官方備註文字" in r_62010.article_full_text
    assert "西醫基層醫療費用審查注意事項-外科.docx" in (r_62010.article_location or "")

    # 2. 83048C：手術節表格註記與 CSV 備註重複，去重後不重印，並含外科 (十八)
    r_83048 = get_rule("83048C", db_path=db_path)
    assert r_83048.article_full_text is not None
    assert "(十八)頭皮腫瘤於髮線以內按83048C頭皮腫瘤申報。" in r_83048.article_full_text
    assert r_83048.article_full_text.count("包括頭皮縫合(suture of scalp)") == 1

    # 3. 藥品 AC25230100 與 AB10000100 完整解開截斷
    r_drug = get_rule("AC25230100", db_path=db_path)
    assert r_drug.article_full_text is not None
    assert "Grade A/B | 4個月" in r_drug.article_full_text
    assert "7.1" in (r_drug.article_location or "")

    r_parent = get_rule("AB10000100", db_path=db_path)
    assert r_parent.article_full_text is not None
    assert "Iloprost" in r_parent.article_full_text and "Sildenafil" in r_parent.article_full_text

    # 4. 來源缺失保護：official_docs_dir 不存在時，既有 official_fulltext 列必須完整保留不被洗空
    missing_dir = tmp_path / "no_such_official_dir"
    stats_missing = build_fulltext_mapping(
        db_path,
        payment_csv_path=rules_dir / "醫療服務給付項目支付標準261119已填支付規定.csv",
        drug_csv_path=rules_dir / "藥品項查詢項目檔261028AI  摘要支付價大於0.csv",
        official_docs_dir=missing_dir,
    )
    assert stats_missing.official_docs_available is False
    assert stats_missing.warnings
    assert get_rule("AC25230100", db_path=db_path).article_full_text == r_drug.article_full_text
    assert get_rule("83048C", db_path=db_path).article_full_text == r_83048.article_full_text

    # 5. replace=True（帶 confirm）移除 99001C 後，孤立 rule_mapping 自動清理，其餘保留
    _write_csv(
        rules_dir / "醫療服務給付項目支付標準261201已填支付規定.csv",
        [
            "診療項目代碼,中文項目名稱,備註,支付規定,生效起日,生效迄日",
            '83048C,頭皮腫瘤,"1.包括頭皮縫合(suture of scalp)2.一般頭皮縫合依創傷處置申報。",審查原則：簡要,20231001,29101231',
            '62010C,皮下腫瘤摘除術,單獨官方備註文字,審查原則：簡要,20231001,29101231',
        ],
    )
    res_rep = sync_latest_rules(
        db_path=db_path,
        rules_dir=str(rules_dir),
        replace=True,
        confirm=REPLACE_CONFIRM_TOKEN,
        official_docs_dir=str(docs_dir),
    )
    assert res_rep.rule_mapping_rows == 4
    conn = sqlite3.connect(db_path)
    mapped_codes = {r[0] for r in conn.execute("SELECT code FROM rule_mapping")}
    conn.close()
    assert "99001C" not in mapped_codes
    assert {"83048C", "62010C", "AC25230100", "AB10000100"} == mapped_codes


def test_fulltext_rendering_expands_full_payment_text_and_excludes_it_from_collapsible():
    """驗證 payment_text 完整原文自動展開（不簡要截斷）；折疊區按下才展開且僅含官方條文全文（不含 payment_text）。"""
    long_62010c_payment = (
        "脂肪瘤如在皮下，以本項目（62010C）申報；脂肪瘤如在深層（如肌肉等），"
        "得以肌肉層或深部組織腫瘤切除術（62009C）項申報。超過10公分以上，得以75602C"
        "（腹壁腫瘤切除術，良性）項申報，同時須檢附患者手術前後之照片，如執行有困難時，"
        "則於病歷繪圖詳細記載大小及部位代替照片。\n\n"
        "痣切除於病歷中未見惡性症候記載者，不予支付62010C及相關病理費用（但先天性黑色素細胞痣不在此限），"
        "但申報如不符合臨床常態分佈者應加強審查。"
    )
    long_official_3000 = "【官方原文】" + ("第一條完整健保給付規定條文內容不可截斷。" * 160)
    assert len(long_official_3000) > 3000

    # Stage 1 月審 HTML 報告
    finding = OrderFinding(
        order_seq="1",
        code="62010C",
        category="2",
        unit_price="1623",
        points="1623",
        flags=("points_over_350",),
        rule_status=STATUS_RESTRICTION,
        rule_name="臉部以外皮膚及皮下腫瘤摘除術",
        source_texts=(
            ("payment_text", long_62010c_payment),
            ("article_full_text", long_official_3000),
        ),
        article_location="西醫基層醫療費用審查注意事項-外科.docx > (十三)",
    )
    case = CaseAudit(
        case_id="MON-62010",
        batch="MONTHLY-202611",
        case_seq="1",
        department="03",
        doctor_code="D1",
        visit_date="1151123",
        primary_diagnosis="D234",
        secondary_diagnoses=(),
        total_points="4500",
        findings=(finding,),
    )
    batch = BatchAudit(
        batch="MONTHLY-202611",
        cases_total=1,
        cases=(case,),
        report={
            "totals": {"cases_flagged": 1, "findings": 1, "rule_status": {STATUS_RESTRICTION: 1}},
            "by_department": {"03": {"cases_flagged": 1, "findings": 1, "rule_status": {STATUS_RESTRICTION: 1}}},
            "by_doctor": {"D1": {"cases_flagged": 1, "findings": 1, "rule_status": {STATUS_RESTRICTION: 1}}},
        },
    )
    html1 = render_batch_report_html(batch)
    # 1. 上方 payment_text 自動展開完整原文（兩段全在，不可簡要截斷）
    m_pay1 = re.search(r'<div class="rule-payment-text">(.*?)</div>', html1, re.S)
    assert m_pay1 and m_pay1.group(1) == long_62010c_payment
    assert html1.index('<div class="rule-payment">') < html1.index('<details class="rule-fulltext"><summary>📜 檢視完整給付規定條文</summary>')
    assert '<details class="rule-fulltext" open' not in html1
    # 2. 折疊區僅包含官方條文全文（3,000+ 字完整不截斷），不包含 payment_text
    assert "官方條文全文（西醫基層醫療費用審查注意事項-外科.docx &gt; (十三)）" in html1
    pre_blocks = re.findall(r'<pre class="rule-text">(.*?)</pre>', html1, re.S)
    assert pre_blocks == [long_official_3000]
    details_block = html1[html1.index('<details class="rule-fulltext">'):]
    assert "給付規定（payment_text）" not in details_block
    assert "痣切除於病歷中未見惡性症候記載者" not in details_block

    # Stage 2/3 統一報告 renderer 行為完全一致
    view = ReviewCaseView(
        case_id="SAMP-62010",
        stage=2,
        header={"醫令": "62010C"},
        kpis={},
        rules=(
            RuleBlock(label="給付規定（payment_text）", text=long_62010c_payment, is_payment_text=True),
            RuleBlock(
                label="條文全文（article_full_text）",
                text=long_official_3000,
                location="西醫基層醫療費用審查注意事項-外科.docx > (十三)",
            ),
        ),
        order_code="62010C",
        order_name="臉部以外皮膚及皮下腫瘤摘除術",
    )
    html2 = render_aggregated_review_html([view], title="抽樣測試")
    m_pay2 = re.search(r'<div class="rule-payment-text">(.*?)</div>', html2, re.S)
    assert m_pay2 and m_pay2.group(1) == long_62010c_payment
    assert html2.index('<div class="rule-payment">') < html2.index('<details class="rule-fulltext"><summary>📜 檢視完整給付規定條文</summary>')
    assert '<details class="rule-fulltext" open' not in html2
    pre_blocks2 = re.findall(r'<pre class="rule-text">(.*?)</pre>', html2, re.S)
    assert pre_blocks2 == [long_official_3000]
    details_block2 = html2[html2.index('<details class="rule-fulltext">'):]
    assert "給付規定（payment_text）" not in details_block2

    # 僅有 payment_text、無 article_full_text 時：直接完整展開，不輸出空折疊框
    view_pay_only = ReviewCaseView(
        case_id="SAMP-PAYONLY",
        stage=2,
        header={"醫令": "62010C"},
        kpis={},
        rules=(RuleBlock(label="給付規定（payment_text）", text=long_62010c_payment, is_payment_text=True),),
        order_code="62010C",
        order_name="臉部以外皮膚及皮下腫瘤摘除術",
    )
    html_only = render_aggregated_review_html([view_pay_only], title="僅payment_text測試")
    assert long_62010c_payment in html_only
    assert '<details class="rule-fulltext">' not in html_only
