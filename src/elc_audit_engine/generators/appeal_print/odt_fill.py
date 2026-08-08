"""紙本申復清單 ODT 注入層（Phase 11 紙本申復清單列印）。

以 stdlib `xml.etree.ElementTree` 直接編輯官方 ODT 的 `content.xml` 表格
單元格文本，再以 `zipfile` 重打包為 .odt（RESEARCH Code Examples 1/2，
spike 實測成功）。無既有 analog——全 codebase 無 ODT/ODF 容器操作先例
（11-PATTERNS.md），本模組以 RESEARCH spike 為基準。

## 模板結構（官方 30396_1/30396_3 ODT 實測，權威契約）

- 9 個 table（每聯 3 個）：頭表(1 row,17 cells)／主表(18 rows)／說明表(4 rows)。
- 主表 row0=大標題、row1=欄位表頭（含 1 個 covered cell＝「傷病名稱」跨行）、
  row2~row16=15 個空資料列（每列 15 cells＝14 資料欄＋1 單價續列）、
  row17=合計列（8 cells：cell[0]「合計」x4、cell[1]「人次」x3、cell[6]「補付金額」x3）。
- 資料列 cell 順序：cell[0]案件分類 cell[1]流水號 cell[2]身份證字號 cell[3]姓名
  cell[4]傷病名稱 cell[5]醫令序 cell[6]內容 cell[7]數量 cell[8]金額 cell[9]理由
  cell[10]審核意見 cell[11]補付數量 cell[12]單價 cell[13]單價續列（留空跳過）
  cell[14]補付金額。
- 頭表 cell 順序：cell[0]代號字碼 cell[1]值 cell[2]醫療院所名稱 cell[3]值
  cell[4]審查科別 cell[5]值 cell[6]原申報類別 cell[7]□送核□補報 cell[8]原申報
  日期 cell[9]年月日 cell[10]空 cell[11]年度 cell[12]值 cell[13]月份 cell[14]值
  cell[15]頁數 cell[16]值。
- 聯間以 `text:soft-page-break` 分隔（2 次）；content.xml 根元素約 21 個 xmlns
  前綴需逐一註冊，否則序列化會出現 ns0/ns1（RESEARCH Pitfall 4）。

## 安全紀律

- **全部欄位值一律經 ET 文本節點寫入（`p.text = value`，自動轉義 `<>&`）**，
  嚴禁字串插值（T-11-01；RESEARCH Pitfall 2）。
- 錯誤訊息只記欄位名/失敗階段，不記欄位值全文（T-11-03，比照
  `AppealXmlEncodingError`）。
- zip 重打包：mimetype 必須第一個寫入且 `ZIP_STORED`（RESEARCH Pitfall 3）。
"""

from __future__ import annotations

import copy
import hashlib
import os
import re
import xml.etree.ElementTree as ET
import zipfile

# ODF 命名空間（實測自官方 content.xml 根元素）。
_TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
_TABLE_NS = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
_OFFICE_NS = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"

_P = f"{{{_TEXT_NS}}}p"
_TABLE = f"{{{_TABLE_NS}}}table"
_TABLE_ROW = f"{{{_TABLE_NS}}}table-row"
_TABLE_CELL = f"{{{_TABLE_NS}}}table-cell"
_SOFT_PAGE_BREAK = f"{{{_TEXT_NS}}}soft-page-break"

# 主表資料列 cell 對應（每列 15 cells；cell[13]＝單價續列，無欄位，留空跳過）。
_ROW_CELLS = (
    ("案件分類", 0),
    ("流水號", 1),
    ("身份證字號", 2),
    ("姓名", 3),
    ("傷病名稱", 4),
    ("醫令序", 5),
    ("內容", 6),
    ("數量", 7),
    ("金額", 8),
    ("理由", 9),
    ("審核意見", 10),
    ("補付數量", 11),
    ("單價", 12),
    ("補付金額", 14),
)

# 頭表值 cell 對應（17 cells；奇數 index 為值欄）。
_HEADER_CELLS = (
    ("代號字碼", 1),
    ("醫療院所名稱", 3),
    ("審查科別", 5),
    ("原申報類別", 7),
    ("原申報日期", 9),
    ("年度", 12),
    ("月份", 14),
)

_MIMETYPE = "application/vnd.oasis.opendocument.text"

# 官方 ODT 中每聯的表格數（頭表/主表/說明表）。
_TABLES_PER_COPY = 3
_MAIN_TOTAL_ROW = 17  # 合計列 row index


class AppealPrintFillError(ValueError):
    """ODT 注入失敗（欄位名/階段，不含欄位值全文——T-11-03）。"""

    def __init__(self, message: str, stage: str | None = None):
        super().__init__(message)
        self.stage = stage


def verify_template_hash(template_path: str, expected_sha256: str | None) -> None:
    """模板 sha256 校驗（T-11-06/A5）。

    Args:
        template_path: 模板 ODT 路徑。
        expected_sha256: 入庫的模板 sha256；None 表示跳過校驗。

    Raises:
        ValueError: 模板被竄改（hash 不符）。
    """
    if expected_sha256 is None:
        return
    digest = hashlib.sha256()
    with open(template_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    if digest.hexdigest().lower() != str(expected_sha256).lower():
        raise ValueError(
            "申復清單模板 sha256 不符，可能已被竄改（階段：verify_template_hash）"
        )


def _register_namespaces(root_el_text: str) -> None:
    """從根元素開標籤註冊全部 xmlns 前綴（含默認命名空間）。

    RESEARCH Pitfall 4：不註冊會導致序列化時出現 ns0/ns1 前綴。
    """
    for m in re.finditer(r'xmlns(?::([A-Za-z0-9_]+))?="([^"]+)"', root_el_text):
        ET.register_namespace(m.group(1) or "", m.group(2))


def _cell_text_value(cell: ET.Element) -> str:
    """讀取 cell 內全部文本（含 text:span，供測試/除錯）。"""
    return "".join(cell.itertext())


def set_cell_text(cell: ET.Element, value: str) -> None:
    """以 ET 文本節點寫入 cell（T-11-01 自動轉義，嚴禁字串插值）。

    找 cell 內第一個 `text:p`，清除其全部子元素（含 `text:span`、
    `text:s` 等殘留，避免尾隨 tail 文本殘留）後以 `p.text = value`
    寫入；無 p 則建立。
    """
    p = cell.find(_P)
    if p is None:
        p = ET.SubElement(cell, _P)
    for child in list(p):
        p.remove(child)
    p.text = value


def _fill_header_cells(head_table: ET.Element, header_fields: dict, page_no: int, total_pages: int) -> None:
    """填頭表值 cell（代號字碼/院所名稱/審查科別/原申報類別/原申報日期/年度/月份/頁數）。"""
    row = head_table.find(_TABLE_ROW)
    if row is None:
        raise AppealPrintFillError("頭表找不到 table-row", stage="fill_header")
    cells = row.findall(_TABLE_CELL)
    for key, idx in _HEADER_CELLS:
        set_cell_text(cells[idx], str(header_fields.get(key, "") or ""))
    # 頁數欄：頭表最後兩個 cell（cell[15]=「頁數」標題、cell[16]=值）
    set_cell_text(cells[-1], f"{page_no}/{total_pages}")


def _fill_main_rows(main_table: ET.Element, page_rows: list[dict]) -> None:
    """填主表 row2~row16 資料列（每列 14 資料欄；cell[13] 單價續列留空跳過）。"""
    rows = main_table.findall(_TABLE_ROW)
    for row_idx, row_data in enumerate(page_rows):
        target = rows[2 + row_idx]
        cells = target.findall(_TABLE_CELL)
        for key, cell_idx in _ROW_CELLS:
            set_cell_text(cells[cell_idx], str(row_data.get(key, "") or ""))


def _fill_total_row(main_table: ET.Element, total_rows: int) -> None:
    """填主表 row17 合計列（語義：cell[0]＝「合計」、數量欄 cell[2]＝該聯人次加總；
    金額與補付數量/單價/補付金額 cell 一律留空——系統不算補付金額、不捏造）。"""
    rows = main_table.findall(_TABLE_ROW)
    if len(rows) <= _MAIN_TOTAL_ROW:
        return
    cells = rows[_MAIN_TOTAL_ROW].findall(_TABLE_CELL)
    set_cell_text(cells[0], "合計")
    set_cell_text(cells[2], str(total_rows))


def _make_copy_group(
    head_table: ET.Element,
    main_table: ET.Element,
    title_p: ET.Element,
    gap_p: ET.Element,
    page_rows: list[dict],
    header_fields: dict,
    page_no: int,
    total_pages: int,
) -> list[ET.Element]:
    """複製「標題＋頭表＋主表」產生一頁的續頁組元素清單（D-06）。

    續頁組不含合計列（row17）與說明表——它們只出現在該聯最後一頁
    （由 fill_template 直接填原始組）。合計列/說明表同頁收尾。

    Returns:
        body 中依序插入的元素清單（標題 p、頭表、空 p、主表）。
    """
    title_cp = copy.deepcopy(title_p)
    head_cp = copy.deepcopy(head_table)
    main_cp = copy.deepcopy(main_table)
    gap_cp = copy.deepcopy(gap_p)

    # 續頁主表移除合計列（row17）；末頁由 fill_template 保留。
    main_rows = main_cp.findall(_TABLE_ROW)
    if len(main_rows) > _MAIN_TOTAL_ROW:
        main_cp.remove(main_rows[_MAIN_TOTAL_ROW])

    _fill_header_cells(head_cp, header_fields, page_no, total_pages)
    _fill_main_rows(main_cp, page_rows)

    return [title_cp, head_cp, gap_cp, main_cp]


def fill_template(
    template_odt_path: str,
    header_fields: dict,
    pages: list[list[dict]],
    output_odt_path: str,
    *,
    expected_sha256: str | None = None,
) -> str:
    """把資料注入官方 ODT 模板並重打包，回傳 output_odt_path。

    Args:
        template_odt_path: 官方/基準模板 .odt 路徑（git-tracked 資產）。
        header_fields: build_header 產出的 7 鍵 dict（代號字碼/醫療院所名稱/
            審查科別/原申報類別/原申報日期/年度/月份）。
        pages: paginate 產出的分頁資料列（每頁一組 build_rows 的 14 鍵 row）。
        output_odt_path: 產出 .odt 路徑。
        expected_sha256: 模板 sha256（T-11-06）；None＝跳過。

    Returns:
        output_odt_path（與傳入相同）。

    Raises:
        FileNotFoundError: 模板路徑不存在。
        ValueError: 模板 hash 不符。
        AppealPrintFillError: 注入/序列化失敗（訊息不含欄位值全文）。
    """
    if not os.path.isfile(template_odt_path):
        raise FileNotFoundError(
            f"申復清單模板不存在（階段：fill_template）：{template_odt_path!r}"
        )
    verify_template_hash(template_odt_path, expected_sha256)

    try:
        with zipfile.ZipFile(template_odt_path, "r") as zin:
            content_raw = zin.read("content.xml").decode("utf-8")
    except (KeyError, OSError) as exc:
        raise AppealPrintFillError(
            "無法讀取模板 content.xml（zip 結構異常）", stage="read_template"
        ) from exc

    _register_namespaces(re.search(r"<office:document-content[^>]*>", content_raw).group(0))

    try:
        tree = ET.fromstring(content_raw)
    except ET.ParseError as exc:
        raise AppealPrintFillError(
            "模板 content.xml 無法解析", stage="parse_template"
        ) from exc

    body = tree.find(f"{{{_OFFICE_NS}}}body/{{{_OFFICE_NS}}}text")
    if body is None:
        raise AppealPrintFillError("找不到 office:body/office:text", stage="locate_body")

    tables = body.findall(_TABLE)
    # 三聯共用相同的 pages（每聯一份醫令明細）。
    total_pages = len(pages)
    for copy_idx in range(len(tables) // _TABLES_PER_COPY):
        base = copy_idx * _TABLES_PER_COPY
        head_table = tables[base]
        main_table = tables[base + 1]
        note_table = tables[base + 2]

        # 定位「標題 p」（頭表前一個兄弟）與「空 p」（頭表後一個兄弟）。
        children = list(body)
        head_pos = children.index(head_table)
        title_p = children[head_pos - 1]
        gap_p = children[head_pos + 1]

        # 該聯頁數 = total_pages；合計列/說明表只在該聯最後一頁。
        if total_pages == 1:
            _fill_header_cells(head_table, header_fields, 1, 1)
            _fill_main_rows(main_table, pages[0])
            _fill_total_row(main_table, len(pages[0]))
            continue

        # >1 頁：在原始組（最後一頁）前插入 (total_pages-1) 個續頁組，
        # 各組間以 text:soft-page-break 分隔。
        insert_at = children.index(title_p)
        inserted: list[ET.Element] = []
        for page_no in range(1, total_pages):  # 1..N-1 頁（續頁）
            if page_no > 1:
                inserted.append(ET.Element(_SOFT_PAGE_BREAK))
            grp = _make_copy_group(
                head_table,
                main_table,
                title_p,
                gap_p,
                pages[page_no - 1],
                header_fields,
                page_no,
                total_pages,
            )
            inserted.extend(grp)
        inserted.append(ET.Element(_SOFT_PAGE_BREAK))
        # 逆序插入，維持正序。
        for el in reversed(inserted):
            body.insert(insert_at, el)

        # 原始組＝該聯最後一頁（含合計列與說明表）。
        _fill_header_cells(head_table, header_fields, total_pages, total_pages)
        _fill_main_rows(main_table, pages[total_pages - 1])
        _fill_total_row(main_table, sum(len(p) for p in pages))

    # 序列化預檢（fail-fast）：不可序列化時 raise 自訂錯誤（T-11-03）。
    try:
        serialized = ET.tostring(tree, encoding="UTF-8", xml_declaration=True)
    except (ValueError, TypeError) as exc:
        raise AppealPrintFillError(
            "content.xml 序列化失敗（資料含無法序列化內容）", stage="serialize"
        ) from exc

    # zip 重打包：mimetype 第一個寫入且 ZIP_STORED，其餘 ZIP_DEFLATED。
    try:
        with zipfile.ZipFile(template_odt_path, "r") as zin:
            infos = zin.infolist()
            with zipfile.ZipFile(output_odt_path, "w", zipfile.ZIP_DEFLATED) as zout:
                zout.writestr("mimetype", _MIMETYPE, compress_type=zipfile.ZIP_STORED)
                for info in infos:
                    if info.filename == "mimetype":
                        continue
                    if info.filename == "content.xml":
                        zout.writestr("content.xml", serialized)
                    else:
                        zout.writestr(info.filename, zin.read(info.filename))
    except OSError as exc:
        raise AppealPrintFillError(
            f"重打包 ODT 失敗（階段：repack）", stage="repack"
        ) from exc

    return output_odt_path
