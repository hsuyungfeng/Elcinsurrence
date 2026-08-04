"""PP-StructureV3 表格結構化 OCR（可選依賴，延遲載入；不可用自動降級）。

紙本抽樣清單（JPEG／掃描 PDF）的**欄位級**結構化：PP-StructureV3 版面解析
→ 表格元素 HTML（`<tr>/<td>`）→ 表頭列對映 `sampling.COLUMN_ALIASES` 契約
→ `SamplingCaseRecord`。比 tesseract 行解析（僅錨定醫令代碼）多出「表頭對齊、
欄位填入」能力，正是「影像辨識填入表單」的目標。

設計（延續誠實降級精神）：
- **延遲載入**：paddleocr 只在首次需要時 import（秒級），未安裝/import 失敗
  時 `parse_image_tables` 回 None → 呼叫端降級回 tesseract 行解析，絕不
  靜默給錯誤結構。
- **D2 不出本機**：全部本地 CPU 推理；模型緩存 `PADDLE_PDX_CACHE_HOME`
  （預設 `~/.cache/elc-paddlex`，本機 `~/.paddlex` 唯讀，2026-08-04 實測）。
- **版本**：paddlepaddle 須釘 3.2.2（3.3.1 CPU 有 oneDNN/PIR bug，見
  deepflash4improve §8.2）。
"""

from __future__ import annotations

import html as html_lib
import os
import re

from .sampling import (
    COLUMN_ALIASES,
    SamplingCaseRecord,
    SamplingImportResult,
    SamplingRejectedRow,
    _row_to_record,
)

# 醫令代碼格式驗證（退路模式過濾表頭/雜訊行）。
_ORDER_CODE_RE = re.compile(r"\d{5}[A-Za-z]")

# paddlex 緩存目錄（模型下載一次、多環境共用；預設路徑 ~/.paddlex 本機唯讀）。
_CACHE_HOME = os.path.expanduser("~/.cache/elc-paddlex")

# 表格 HTML 的列/儲存格（PP-StructureV3 產出為規範格式，無巢狀表格）。
_TR_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TD_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)

_engine = None  # 惰性單例（延遲載入）


def _get_engine():
    """建立（或取用）PP-StructureV3 引擎；不可用回 None。"""
    global _engine
    if _engine is not None:
        return _engine
    try:
        os.environ.setdefault("PADDLE_PDX_CACHE_HOME", _CACHE_HOME)
        from paddleocr import PPStructureV3

        _engine = PPStructureV3(lang="ch")
        return _engine
    except Exception:
        # 未安裝／依賴缺失／初始化失敗 → 呼叫端降級 tesseract（不拋異常）。
        return None


def _extract_rows(table_html: str) -> list[list[str]]:
    """從表格 HTML 提取 (列, 儲存格) 結構，清除空白與 HTML 實體。"""
    rows: list[list[str]] = []
    for tr in _TR_ROW_RE.findall(table_html):
        cells = [
            html_lib.unescape(re.sub(r"<[^>]+>", "", td)).strip()
            for td in _TD_CELL_RE.findall(tr)
        ]
        if any(cells):
            rows.append(cells)
    return rows


def _match_header(row: list[str]) -> dict[str, int] | None:
    """表頭列 → 欄位名→index 對映；命中 order_code 才視為有效表頭。"""
    mapping: dict[str, int] = {}
    for field, aliases in COLUMN_ALIASES.items():
        for idx, cell in enumerate(row):
            if cell.lower() in {a.lower() for a in aliases}:
                mapping[field] = idx
                break
    if "order_code" not in mapping:
        return None
    return mapping


def parse_sampling_tables(htmls: list[str]) -> SamplingImportResult:
    """多個表格 HTML → 抽樣案件記錄（去重表頭、缺 order_code 拒絕）。

    來源標記 `source="paddle"`（PP-StructureV3 結構化），每筆保留原始辨識行。
    無契約表頭對映時退路：第一欄視為醫令代碼＋格式驗證（5 數字+1 字母），
    表頭/雜訊行（格式不符）進 rejected，不靜默進記錄。
    """
    records: list[SamplingCaseRecord] = []
    rejected: list[SamplingRejectedRow] = []
    seen_codes: set[str] = set()
    row_no = 0

    for html_text in htmls:
        rows = _extract_rows(html_text)
        if not rows:
            continue
        mapping = _match_header(rows[0])
        fallback = mapping is None
        data_rows = rows[1:] if mapping is not None else rows
        if fallback:
            # 退路：假設「醫令代碼」在第一欄、「醫令名稱」在第二欄（表格常如此）。
            mapping = {"order_code": 0, "order_name": 1}

        for cells in data_rows:
            row_no += 1
            rec = _row_to_record(cells, mapping, source="paddle")
            if not rec.order_code:
                rejected.append(
                    SamplingRejectedRow(
                        row_number=row_no,
                        reason="缺少必填欄位「醫令代碼」",
                        raw=tuple(cells),
                    )
                )
                continue
            if fallback and not _ORDER_CODE_RE.fullmatch(rec.order_code):
                rejected.append(
                    SamplingRejectedRow(
                        row_number=row_no,
                        reason="非醫令代碼格式（疑似表頭或雜訊列）",
                        raw=tuple(cells),
                    )
                )
                continue
            if rec.order_code in seen_codes:
                rejected.append(
                    SamplingRejectedRow(
                        row_number=row_no,
                        reason="重複的醫令代碼（跨頁/重複表頭，已略過）",
                        raw=tuple(cells),
                    )
                )
                continue
            seen_codes.add(rec.order_code)
            records.append(rec)

    return SamplingImportResult(
        records=tuple(records),
        rejected=tuple(rejected),
        source="paddle",
    )


def _collect_table_htmls(predict_result) -> list[str]:
    """從 PP-StructureV3 predict 結果收集所有 `table` 元素的 HTML。"""
    htmls: list[str] = []
    for page in predict_result:
        for block in page.get("parsing_res_list", []):
            if getattr(block, "label", None) == "table":
                content = getattr(block, "content", "") or ""
                if "<table" in content.lower():
                    htmls.append(content)
    return htmls


def parse_image_tables(path: str) -> SamplingImportResult | None:
    """對單張影像跑 PP-StructureV3 表格結構化。

    Returns:
        SamplingImportResult（source="paddle"）；引擎不可用／無表格元素時
        回 None → 呼叫端應降級回 tesseract 行解析。
    """
    engine = _get_engine()
    if engine is None:
        return None
    try:
        result = engine.predict(input=path)
    except Exception:
        return None
    htmls = _collect_table_htmls(result)
    if not htmls:
        return None
    parsed = parse_sampling_tables(htmls)
    # 表格存在但完全無法對應契約（連 order_code 都沒有）→ 同樣降級。
    if not parsed.records:
        return None
    return parsed


def parse_pdf_tables(path: str) -> SamplingImportResult | None:
    """掃描 PDF → pdftoppm 渲染每頁 → PP-StructureV3 → 合併結果。

    Returns:
        SamplingImportResult（source="paddle"）；引擎不可用／無表格元素時
        回 None → 呼叫端降級（tesseract 全文 OCR 行解析）。
    """
    import shutil
    import tempfile

    from .media import MediaExtractError, render_pdf_pages

    out_dir = tempfile.mkdtemp(prefix="elc_pdf_tbl_")
    try:
        try:
            pages = render_pdf_pages(path, out_dir)
        except MediaExtractError:
            return None
        engine = _get_engine()
        if engine is None:
            return None
        htmls: list[str] = []
        for page in pages:
            try:
                result = engine.predict(input=page)
            except Exception:
                continue  # 單頁失敗不阻斷其餘頁面（誠實降級精神）
            htmls.extend(_collect_table_htmls(result))
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
    if not htmls:
        return None
    parsed = parse_sampling_tables(htmls)
    return parsed if parsed.records else None
