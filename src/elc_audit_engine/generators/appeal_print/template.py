"""紙本申復清單壓縮基準模板產生器（Phase 11 一次性布局壓縮）。

**角色**：一次性把官方 ODT（`30396_1_1050105-1門診診療費用申復清單.odt`）
壓縮成每聯一頁的 `*_print_base.odt` 基準模板＋sha256 檔，產物入 git 版控
（T-11-06/A5），**不於每次 render 重複調參**（11-PATTERNS.md）。運行：
`render_appeal_print/write_appeal_print` 消費基準模板，由
`odt_fill.fill_template` 注入資料後經 soffice 轉 PDF。

## 版面問題（RESEARCH Pitfall 1，本 session 實測）

官方 ODT 直接轉 PDF 是 **9 頁**（每聯 3 頁）：標題+頭表+主表表頭一頁、
主表資料行+合計列一頁、說明表一頁。根因（content.xml/styles.xml 實測）：

1. **書寫佈局網格**：頁面 `style:layout-grid-mode="line"`（45 線）＋默認
   段落 `style:snap-to-layout-grid="true"`，使所有文字行吸附到約 18.7pt
   的網格上，空段落/行被放大成整行網格高度——這是 9 頁的最大元兇。
2. **資料行段落 line-height=0.3333in（24pt）**＋min-row-height=0.2361in，
   15 行實際渲染約 29.3pt/行。
3. **聯間分頁**：`text:soft-page-break` 是**軟**分頁符，內容壓短後不會
   強制分頁，必須靠每聯標題段 `fo:break-before="page"` 維持「每聯一頁」。

## 收斂迭代過程（Golden＝官方 `30396_4` PDF，每聯一頁、資料行約 27pt）

實驗依序（每次以 soffice 轉 PDF + pypdf 數頁 + pdftotext -bbox 量測）：

| 輪 | 變更 | 頁數 | bbox 行高/頁底 | 結果 |
|----|------|------|----------------|------|
| v0 | 關網格＋0.2in 行高＋全邊距壓縮 | 3 | — | 頁數對但聯間錯位（soft-page-break 不分頁） |
| v1 | 僅關網格 | 3 | — | 同上錯位 |
| v2 | 關網格＋聯標題 break-before=page | 6 | — | 每聯 2 頁（行高未壓） |
| v3 | 同 v2＋資料行 0.2in＋標題行高 120%＋邊距 0.5/0.1in | 3 | 行高 29.3pt／頁底 799pt | 每聯一頁，微溢出 |
| v4 | 資料行 0.18in | **3** | **行高 26.4pt／頁底 779.3pt** | **✅ 收斂（對齊 Golden 27pt/779pt）** |
| v5 | 資料行 0.16in | 3 | 行高 23.5pt／頁底 735.8pt | 備選（更緊） |

## 最終採用的壓縮參數（v4）

- 頁面邊距：left/right `0.5in`、top/bottom `0.1in`
- 佈局網格：`layout-grid-mode=none`；默認段落 `snap-to-layout-grid=false`
- 資料行（row2~16）段落 line-height＋行 min-row-height：`0.18in`
- 主表表頭行 row0 min-row-height：`0.35in`
- 頭表 min-row-height：`0.45in`
- 合計列（row17）min-row-height：`0.2in`
- 標題段 line-height：`120%`
- 聯標題段強制 `fo:break-before="page"`（補償 soft-page-break 不強制分頁）
- 說明表**不調整**（模板實測 v4 頁底 779.3pt，完整落頁）

收斂判準：soffice 轉 PDF 總頁數＝3（每聯一頁）且每聯的合計列與說明表
同頁；15 行醫令時 3 頁、16 行時 3×2＝6 頁（D-06 分頁保持）。

## 輸出

- `out_odt`：壓縮基準模板（入 git，官方模板版控資產例外）
- `sha256_out`：產物 ODT 的 sha256（供 `odt_fill.verify_template_hash`
  生成前校驗，A5/T-11-06）

**安全紀律**：本模組不改動欄位值注入（那是 `odt_fill` 職責），只做
樣式/結構層的 layout 壓縮；全部寫入經 `xml.etree` 節點操作，無字串
拼接 XML。
"""

from __future__ import annotations

import hashlib
import os
import re
import xml.etree.ElementTree as ET
import zipfile

from elc_audit_engine.generators.appeal_print.odt_fill import AppealPrintFillError

_MIMETYPE = "application/vnd.oasis.opendocument.text"

# 命名空間（ODF；與 odt_fill.py 一致）。
_NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}
_S = "{%s}" % _NS["style"]
_FO = "{%s}" % _NS["fo"]
_TXT = "{%s}" % _NS["text"]

# ── 收斂參數（v4，見模組 docstring）───────────────────────────────
_MARGIN_LEFT = "0.5in"
_MARGIN_RIGHT = "0.5in"
_MARGIN_TOP = "0.1in"
_MARGIN_BOTTOM = "0.1in"
_DATA_ROW_LINE_HEIGHT = "0.18in"   # 資料行段落 line-height（15 行×~26.4pt）
_DATA_ROW_MIN_HEIGHT = "0.18in"    # 資料行 min-row-height
_HEADER_ROW_MIN_HEIGHT = "0.45in"  # 頭表行
_MAIN_ROW0_MIN_HEIGHT = "0.35in"   # 主表大標題行
_TOTAL_ROW_MIN_HEIGHT = "0.2in"    # 主表合計列
_TITLE_LINE_HEIGHT = "120%"        # 標題段（300% → 120%）
_GRID_MODE = "none"                # 關閉佈局網格（9 頁主因）

# 官方 ODT 的 min-row-height 值 → 壓縮後值（僅 v4 影響到的行高）。
_ROW_HEIGHT_MAP = {
    "0.2361in": _DATA_ROW_MIN_HEIGHT,  # 資料行 row2~16（15 行）
    "0.4875in": _MAIN_ROW0_MIN_HEIGHT,  # 主表 row0 大標題
    "0.6131in": _HEADER_ROW_MIN_HEIGHT,  # 頭表（每聯）
}
# 說明表行高：v4 決定不調整（完整落頁），保留原值。
_ROW_HEIGHT_MAP_NOTE = {}


def _iter_all(el: ET.Element):
    """深度優先走訪整棵樹（含自身）。"""
    yield el
    for child in el:
        yield from _iter_all(child)


def _register_namespaces_from(raw: str) -> None:
    """從 XML 根元素註冊全部 xmlns 前綴（避免 ET 序列化出現 ns0/ns1）。"""
    root_open = re.search(r"<office:[^ >]*[^>]*>", raw)
    head = root_open.group(0) if root_open else ""
    for m in re.finditer(r'xmlns(?::([A-Za-z0-9_]+))?="([^"]+)"', head):
        ET.register_namespace(m.group(1) or "", m.group(2))


def _parse(raw: str) -> ET.Element:
    _register_namespaces_from(raw)
    return ET.fromstring(raw)


def _serialize(root: ET.Element) -> bytes:
    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)


def _adjust_style_heights(croot: ET.Element) -> None:
    """自動樣式層：壓縮資料行/表頭行/合計列 min-row-height，資料行 line-height。"""
    for el in list(_iter_all(croot)):
        if el.tag != _S + "style":
            continue
        family = el.get(_S + "family")
        if family == "table-row":
            props = el.find(_S + "table-row-properties")
            if props is None:
                continue
            mh = props.get(_FO + "min-row-height")
            if mh in _ROW_HEIGHT_MAP:
                props.set(_FO + "min-row-height", _ROW_HEIGHT_MAP[mh])
            elif mh in _ROW_HEIGHT_MAP_NOTE:
                props.set(_FO + "min-row-height", _ROW_HEIGHT_MAP_NOTE[mh])
        elif family == "paragraph":
            pp = el.find(_S + "paragraph-properties")
            if pp is None:
                continue
            # 資料行段落（官方 line-height=0.3333in）→ 0.18in
            if pp.get(_FO + "line-height") == "0.3333in":
                pp.set(_FO + "line-height", _DATA_ROW_LINE_HEIGHT)
            # 標題段（line-height=300%）→ 120%
            elif pp.get(_FO + "line-height") == "300%":
                pp.set(_FO + "line-height", _TITLE_LINE_HEIGHT)


def _force_break_before_copies(croot: ET.Element) -> None:
    """每個 soft-page-break 後的聯標題段強制 `fo:break-before="page"`。

    `text:soft-page-break` 是軟分頁符：內容壓短後不保證分頁（實測 v0/v1
    三聯黏在一起），必須讓每聯首元素（標題段）強制從新頁開始，維持
    「每聯一頁」。第一/二聯標題段官方已有 break-before=page（樣式
    P1/P687），此處補上第三聯（P1374）及其他任何缺漏。
    """
    body = croot.find(f"{{{_NS['office']}}}body/{{{_NS['office']}}}text")
    if body is None:
        return
    children = list(body)
    soft = "{%s}soft-page-break" % _NS["text"]
    for idx, el in enumerate(children):
        if el.tag == soft and idx + 1 < len(children) and children[idx + 1].tag == _TXT + "p":
            style_name = children[idx + 1].get(_TXT + "style-name")
            if not style_name:
                continue
            for style_el in _iter_all(croot):
                if (
                    style_el.tag == _S + "style"
                    and style_el.get(_S + "family") == "paragraph"
                    and style_el.get(_S + "name") == style_name
                ):
                    pp = style_el.find(_S + "paragraph-properties")
                    if pp is None:
                        pp = ET.SubElement(style_el, _S + "paragraph-properties")
                    if pp.get(_FO + "break-before") != "page":
                        pp.set(_FO + "break-before", "page")


def _adjust_styles_xml(sroot: ET.Element) -> None:
    """styles.xml：頁面邊距 + 關閉佈局網格 + 默認段落取消吸附網格。"""
    layout = sroot.find(f".//{_S}page-layout-properties")
    if layout is not None:
        layout.set(_FO + "margin-left", _MARGIN_LEFT)
        layout.set(_FO + "margin-right", _MARGIN_RIGHT)
        layout.set(_FO + "margin-top", _MARGIN_TOP)
        layout.set(_FO + "margin-bottom", _MARGIN_BOTTOM)
        layout.set(_S + "layout-grid-mode", _GRID_MODE)
    for ds in sroot.iter():
        if ds.tag == _S + "default-style" and ds.get(_S + "family") == "paragraph":
            pp = ds.find(_S + "paragraph-properties")
            if pp is not None:
                pp.set(_S + "snap-to-layout-grid", "false")


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_print_base(
    src_odt: str,
    out_odt: str,
    *,
    sha256_out: str,
) -> str:
    """把官方 ODT 壓縮成每聯一頁的基準模板，並寫出 sha256 檔。

    Args:
        src_odt: 官方 ODT 路徑（`30396_1`，git-tracked 版控資產）。
        out_odt: 輸出壓縮基準模板路徑。
        sha256_out: 產物 sha256 檔路徑（內容＝產物 hex digest）。

    Returns:
        out_odt 路徑。

    Raises:
        FileNotFoundError: 來源模板不存在。
        AppealPrintFillError: zip/XML 處理失敗（訊息不含值全文）。
    """
    if not os.path.isfile(src_odt):
        raise FileNotFoundError(
            f"申復清單官方模板不存在（階段：build_print_base）：{src_odt!r}"
        )
    try:
        with zipfile.ZipFile(src_odt, "r") as zin:
            entries = {i.filename: zin.read(i.filename) for i in zin.infolist()}
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        raise AppealPrintFillError(
            "無法讀取官方模板 zip 結構", stage="build_print_base:read"
        ) from exc

    try:
        styles_raw = entries["styles.xml"].decode("utf-8")
        content_raw = entries["content.xml"].decode("utf-8")
    except KeyError as exc:
        raise AppealPrintFillError(
            "官方模板缺少 styles.xml/content.xml", stage="build_print_base:entries"
        ) from exc

    sroot = _parse(styles_raw)
    croot = _parse(content_raw)
    _adjust_styles_xml(sroot)
    _adjust_style_heights(croot)
    _force_break_before_copies(croot)

    out_dir = os.path.dirname(os.path.abspath(out_odt))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    try:
        with zipfile.ZipFile(out_odt, "w", zipfile.ZIP_DEFLATED) as zout:
            zout.writestr("mimetype", _MIMETYPE, compress_type=zipfile.ZIP_STORED)
            for name, data in entries.items():
                if name == "mimetype":
                    continue
                if name == "styles.xml":
                    zout.writestr(name, _serialize(sroot))
                elif name == "content.xml":
                    zout.writestr(name, _serialize(croot))
                else:
                    zout.writestr(name, data)
    except OSError as exc:
        raise AppealPrintFillError(
            "重打包壓縮基準模板失敗", stage="build_print_base:repack"
        ) from exc

    digest = _sha256_file(out_odt)
    sha_dir = os.path.dirname(os.path.abspath(sha256_out))
    if sha_dir:
        os.makedirs(sha_dir, exist_ok=True)
    with open(sha256_out, "w", encoding="utf-8") as f:
        f.write(digest + "\n")

    return out_odt


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3:
        print("用法: uv run python -m elc_audit_engine.generators.appeal_print.template <src.odt> <out_base.odt>", file=sys.stderr)
        raise SystemExit(1)
    src = sys.argv[1]
    out = sys.argv[2]
    sha = os.path.splitext(out)[0] + ".sha256"
    result = build_print_base(src, out, sha256_out=sha)
    print(f"wrote {result}")
    print(f"wrote {sha} ({_sha256_file(out)})")
