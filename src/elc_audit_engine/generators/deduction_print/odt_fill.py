"""核減明細 ODT 注入層（Phase 13）。

動態複製表格列 (table-row) 並注入資料，重打包回 ODT。
"""

from __future__ import annotations

import copy
import os
import re
import xml.etree.ElementTree as ET
import zipfile

from .field_mapping import ROW_KEYS, HEADER_KEYS

_TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
_TABLE_NS = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
_OFFICE_NS = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"

_P = f"{{{_TEXT_NS}}}p"
_TABLE = f"{{{_TABLE_NS}}}table"
_TABLE_ROW = f"{{{_TABLE_NS}}}table-row"
_TABLE_CELL = f"{{{_TABLE_NS}}}table-cell"

_MIMETYPE = "application/vnd.oasis.opendocument.text"

class DeductionPrintFillError(ValueError):
    """ODT 注入失敗"""
    def __init__(self, message: str, stage: str | None = None):
        super().__init__(message)
        self.stage = stage

def _register_namespaces(root_el_text: str) -> None:
    for m in re.finditer(r'xmlns(?::([A-Za-z0-9_]+))?="([^"]+)"', root_el_text):
        ET.register_namespace(m.group(1) or "", m.group(2))

def set_cell_text(cell: ET.Element, value: str) -> None:
    """安全寫入 cell 文本 (防禦 T-13-01 XML Injection)"""
    p = cell.find(_P)
    if p is None:
        p = ET.SubElement(cell, _P)
    for child in list(p):
        p.remove(child)
    p.text = value

def fill_template(
    template_odt_path: str,
    header_fields: dict[str, str],
    rows: list[dict[str, str]],
    output_odt_path: str,
) -> str:
    """將動態列與表頭資料寫入 ODT。"""
    try:
        with zipfile.ZipFile(template_odt_path, "r") as zin:
            content_raw = zin.read("content.xml").decode("utf-8")
    except (KeyError, OSError) as exc:
        raise DeductionPrintFillError("無法讀取模板 content.xml", stage="read_template") from exc

    _register_namespaces(re.search(r"<office:document-content[^>]*>", content_raw).group(0))

    try:
        tree = ET.fromstring(content_raw)
    except ET.ParseError as exc:
        raise DeductionPrintFillError("模板 content.xml 無法解析", stage="parse_template") from exc

    body = tree.find(f"{{{_OFFICE_NS}}}body/{{{_OFFICE_NS}}}text")
    if body is None:
        raise DeductionPrintFillError("找不到 office:body/office:text", stage="locate_body")

    tables = body.findall(_TABLE)
    if len(tables) < 1:
        raise DeductionPrintFillError("找不到表格", stage="locate_table")
        
    # Replace header placeholders globally
    for table in tables:
        for row in table.findall(_TABLE_ROW):
            for cell in row.findall(_TABLE_CELL):
                text = "".join(cell.itertext())
                for key in HEADER_KEYS:
                    placeholder = f"{{{key}}}"
                    if placeholder in text:
                        new_val = text.replace(placeholder, header_fields.get(key, ""))
                        set_cell_text(cell, new_val)
                        text = new_val
    
    # 尋找包含 {序號} 的資料列作為 prototype
    data_row_idx = -1
    prototype_row = None
    target_table = None
    
    for table in tables:
        all_rows = table.findall(_TABLE_ROW)
        for idx, row in enumerate(all_rows):
            text = "".join(row.itertext())
            if "{序號}" in text:
                data_row_idx = idx
                prototype_row = row
                target_table = table
                break
        if prototype_row is not None:
            break
            
    if prototype_row is None:
        raise DeductionPrintFillError("找不到包含 {序號} 的 prototype row", stage="locate_prototype")
        
    main_table = target_table
    all_rows = main_table.findall(_TABLE_ROW)
    
    # Identify which cell index maps to which ROW_KEY
    cell_mapping = {}
    proto_cells = prototype_row.findall(_TABLE_CELL)
    for c_idx, cell in enumerate(proto_cells):
        text = "".join(cell.itertext()).strip()
        for key in ROW_KEYS:
            if f"{{{key}}}" in text:
                cell_mapping[key] = c_idx
                
    # Now generate new rows
    insert_idx = list(main_table).index(prototype_row)
    main_table.remove(prototype_row)
    
    for row_data in rows:
        new_row = copy.deepcopy(prototype_row)
        new_cells = new_row.findall(_TABLE_CELL)
        for key, c_idx in cell_mapping.items():
            val = row_data.get(key, "")
            # Need to retain other parts if not pure placeholder?
            # Actually, standard is pure placeholder in the cell
            set_cell_text(new_cells[c_idx], str(val))
        main_table.insert(insert_idx, new_row)
        insert_idx += 1
        
    try:
        serialized = ET.tostring(tree, encoding="UTF-8", xml_declaration=True)
    except (ValueError, TypeError) as exc:
        raise DeductionPrintFillError("content.xml 序列化失敗", stage="serialize") from exc

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
        raise DeductionPrintFillError("重打包 ODT 失敗", stage="repack") from exc

    return output_odt_path
