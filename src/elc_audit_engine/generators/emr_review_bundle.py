"""電子病歷審查包（EMR review bundle）：每案一組 XML（核算）＋ HTML（審查，影像內嵌），打包成 ZIP 上傳。

依 `emr-batch-packaging-naming-spec.md`：
- 檔名 11 碼：第一階層(2) ＋ 資料屬性(1, A/B/C/D) ＋ 案件分類(2) ＋ 流水號(6)，半形英數字。
- ZIP 檔名：`{醫事機構代碼10碼}_{系統日期民國7碼}_{序號3碼}.zip`。
- 單包上限 500MB，超過 450MB 即切下一包（序號遞增）。

依使用者確認（2026-11-09）：
- XML 採既有 Big5 抽審格式（`sampling_xml.build_sampling_xml`），供健保局電腦核算。
- HTML 供審查醫師閱覽，影像以 base64 內嵌；影像先縮圖（長邊 ≤ 1600px、JPEG 品質 80）。
- HTML 與 XML 一併放入同一 ZIP 上傳。

安全：病患資料只存在於產出的檔案中；本模組不寫入日誌。
"""

from __future__ import annotations

import base64
import html
import io
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from elc_audit_engine.generators.sampling_xml import build_sampling_xml

MAX_IMAGE_LONG_SIDE = 1600
JPEG_QUALITY = 80
ZIP_SPLIT_BYTES = 450 * 1024 * 1024  # 超過即切包
ZIP_HARD_LIMIT_BYTES = 500 * 1024 * 1024

_NAME11_RE = re.compile(r"^[A-Za-z0-9]{11}$")
_FACILITY_RE = re.compile(r"^[0-9]{10}$")
_DOC_CLASSES = frozenset({"A", "B", "C", "D"})


class BundleError(ValueError):
    """輸入不符合規範（例如檔名格式、機構代碼位數）。"""


def build_base_name(tier1: str, doc_class: str, case_class: str, seq: str) -> str:
    """組 11 碼檔名基底。例：build_base_name('12','A','03','123345') → '12A03123345'。"""
    if not re.fullmatch(r"[0-9]{2}", tier1 or ""):
        raise BundleError("第一階層代碼須為 2 碼數字")
    if doc_class not in _DOC_CLASSES:
        raise BundleError("資料屬性須為 A／B／C／D")
    if not re.fullmatch(r"[0-9]{2}", case_class or ""):
        raise BundleError("案件分類代碼須為 2 碼數字")
    if not re.fullmatch(r"[0-9]{1,6}", seq or ""):
        raise BundleError("流水號須為 1–6 位數字")
    name = f"{tier1}{doc_class}{case_class}{seq.zfill(6)}"
    if not _NAME11_RE.match(name):  # 防禦性檢查：必須精準 11 碼半形英數字
        raise BundleError("產生的檔名不符 11 碼規範")
    return name


def build_zip_name(facility_code: str, roc_date: str, serial: int) -> str:
    """ZIP 檔名：`{機構代碼10}_{民國7碼}_{序號3}.zip`。"""
    if not _FACILITY_RE.match(facility_code or ""):
        raise BundleError("醫事機構代碼須為 10 碼數字")
    if not re.fullmatch(r"[0-9]{7}", roc_date or ""):
        raise BundleError("系統日期須為民國 7 碼（如 1150109）")
    if not 1 <= serial <= 999:
        raise BundleError("序號須介於 1–999")
    return f"{facility_code}_{roc_date}_{serial:03d}.zip"


def compress_image(data: bytes) -> bytes | None:
    """影像縮圖並轉 JPEG（長邊 ≤ 1600px、品質 80）。無法解析者回傳 None（不致整包失敗）。"""
    try:
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover - 依賴缺失時明確降級
        return None
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            img.thumbnail((MAX_IMAGE_LONG_SIDE, MAX_IMAGE_LONG_SIDE))
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            return out.getvalue()
    except Exception:
        return None


@dataclass(frozen=True)
class ReviewImage:
    caption: str
    jpeg: bytes


def _soap_html(soap: dict[str, str] | None, note: str | None = None) -> str:
    if not soap:
        return "<p class=\"missing\">本案無 SOAP 紀錄。</p>"
    prefix = f"<p class=\"missing\">{html.escape(note)}</p>" if note else ""
    rows = "".join(
        f"<tr><th>{label}</th><td>{html.escape(str(soap.get(key) or ''))}</td></tr>"
        for key, label in (("s", "S"), ("o", "O"), ("a", "A"), ("p", "P"))
    )
    return prefix + f"<table class=\"soap\">{rows}</table>"


def render_review_html(
    *,
    case_title: str,
    soap: dict[str, str] | None,
    orders: Iterable[dict[str, Any]],
    images: Iterable[ReviewImage],
    doctor_signature: str | None = None,
    soap_note: str | None = None,
) -> str:
    """審查用 HTML（自包含，影像 base64 內嵌）。SOAP、醫令、影像、電子簽章區依序排列。"""
    order_rows = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(o.get(k) or ''))}</td>" for k in ("code", "name", "points")) + "</tr>"
        for o in orders
    )
    imgs = []
    for img in images:
        b64 = base64.b64encode(img.jpeg).decode("ascii")
        imgs.append(
            f"<figure><img alt=\"{html.escape(img.caption)}\" src=\"data:image/jpeg;base64,{b64}\">"
            f"<figcaption>{html.escape(img.caption)}</figcaption></figure>"
        )
    sig = html.escape(doctor_signature) if doctor_signature else "（醫師電子簽章憑證待附）"
    return (
        "<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(case_title)}</title>"
        "<style>body{font-family:sans-serif;margin:24px;color:#111}"
        "table{border-collapse:collapse;width:100%;margin-bottom:12px}"
        "th,td{border:1px solid #bbb;padding:6px;vertical-align:top;text-align:left}"
        "th{background:#f3f4f6;width:70px}figure{display:inline-block;margin:8px;max-width:360px}"
        "img{max-width:100%}.missing{color:#b45309}.sig{margin-top:18px;border-top:1px solid #999;padding-top:8px}"
        "</style></head><body>"
        f"<h1>{html.escape(case_title)}</h1>"
        "<h2>SOAP 紀錄</h2>" + _soap_html(soap, soap_note)
        + "<h2>醫令</h2><table><tr><th>代碼</th><th>名稱</th><th>點數</th></tr>" + order_rows + "</table>"
        + "<h2>影像佐證</h2>" + ("".join(imgs) or "<p class=\"missing\">無影像佐證。</p>")
        + f"<div class=\"sig\">醫師簽章：{sig}</div>"
        + "</body></html>"
    )


@dataclass(frozen=True)
class CaseBundle:
    base_name: str
    xml_bytes: bytes
    html_bytes: bytes

    def files(self) -> dict[str, bytes]:
        return {f"{self.base_name}.xml": self.xml_bytes, f"{self.base_name}.html": self.html_bytes}


def build_case_bundle(
    *,
    base_name: str,
    xml_payload: dict[str, Any],
    case_title: str,
    soap: dict[str, str] | None,
    orders: Iterable[dict[str, Any]],
    images: Iterable[ReviewImage],
    doctor_signature: str | None = None,
    soap_note: str | None = None,
) -> CaseBundle:
    """組單案：XML（Big5，核算）與 HTML（審查）。檔名須為 11 碼。"""
    if not _NAME11_RE.match(base_name):
        raise BundleError("檔名基底須為 11 碼半形英數字")
    xml_bytes = build_sampling_xml(xml_payload)
    html_text = render_review_html(
        case_title=case_title, soap=soap, orders=orders, images=images, doctor_signature=doctor_signature,
        soap_note=soap_note,
    )
    return CaseBundle(base_name=base_name, xml_bytes=xml_bytes, html_bytes=html_text.encode("utf-8"))


def pack_zips(
    bundles: Iterable[CaseBundle],
    *,
    facility_code: str,
    roc_date: str,
    split_bytes: int = ZIP_SPLIT_BYTES,
) -> list[tuple[str, bytes]]:
    """將案件組合成 ZIP 清單；超過 `split_bytes` 即切下一包（序號遞增）。回傳 [(zip檔名, bytes)]。"""
    groups: list[list[CaseBundle]] = [[]]
    sizes = [0]
    for bundle in bundles:
        size = len(bundle.xml_bytes) + len(bundle.html_bytes)
        if groups[-1] and sizes[-1] + size > split_bytes:
            groups.append([])
            sizes.append(0)
        groups[-1].append(bundle)
        sizes[-1] += size

    out: list[tuple[str, bytes]] = []
    for serial, group in enumerate(groups, start=1):
        if not group:
            continue
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for bundle in group:
                for name, data in bundle.files().items():
                    zf.writestr(name, data)
        data = buf.getvalue()
        if len(data) > ZIP_HARD_LIMIT_BYTES:
            raise BundleError("單一 ZIP 超過 500MB 上限，請縮小案件批次")
        out.append((build_zip_name(facility_code, roc_date, serial), data))
    return out


__all__ = [
    "BundleError",
    "CaseBundle",
    "ReviewImage",
    "build_base_name",
    "build_case_bundle",
    "build_zip_name",
    "compress_image",
    "pack_zips",
    "render_review_html",
]
