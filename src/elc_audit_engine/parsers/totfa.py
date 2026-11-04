"""TOTFA.zip 當月申報總檔解析（Phase 15-01）與高風險門檻篩選。

- 讀取：以記憶體方式開啟 zip，只取 `TOTFA.xml`（不解壓到磁碟；壓縮檔屬
  不可信輸入），解壓後大小設上限防 zip bomb。編碼與結構沿用
  `submission_xml.parse_submission_xml_bytes`（宣告 Big5 → 逐步回退）。
- 批次：由 `tdata.t3`（費用年月，民國 YYYMM）推得 `MONTHLY-YYYYMM`。
- 篩選：純函式，**只標記、不刪除**原始醫令。
  - 醫令點數 `p12` > 350
  - 藥品單價 `p11` > 5（藥品行 `p3 == "4"`）
- 案件 ID：內容雜湊 `MON-…`。同批次同內容 → 同 ID（重匯入冪等）；
  同批次內完全相同的多筆案件以出現順序區分（保留真實重複的申報列）。

欄位語意以專案規格為準（`.planning/intel/constraints.md`、03-CONTEXT.md）：
p10＝總量、p11＝單價、p12＝點數。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from typing import BinaryIO

from elc_audit_engine.services.date_utils import ROC_OFFSET
from elc_audit_engine.parsers.models import (
    OrderRecord,
    SubmissionCase,
    SubmissionParseResult,
)
from elc_audit_engine.parsers.submission_xml import (
    SubmissionXmlError,
    parse_submission_xml_bytes,
)

TOTFA_XML_NAME = "TOTFA.xml"
# 解壓後 XML 大小上限（實檔約 0.8MB，留足餘裕但擋 zip bomb）。
MAX_TOTFA_XML_BYTES = 64 * 1024 * 1024

ORDER_POINTS_THRESHOLD = Decimal(350)
DRUG_UNIT_PRICE_THRESHOLD = Decimal(5)
# 藥品醫令類別（TOTFA.xml 實測：p3=4 的行帶有 p5 用量、p7 頻率、p9 途徑）。
DRUG_CATEGORY = "4"

BATCH_PREFIX = "MONTHLY-"
CASE_ID_PREFIX = "MON-"
_ROC_YEAR_MONTH_RE = re.compile(r"^(\d{2,3})(\d{2})$")


# ── 讀取 ──────────────────────────────────────────────────────────


def _open_zip(source: str | os.PathLike[str] | bytes | BinaryIO) -> zipfile.ZipFile:
    if isinstance(source, (bytes, bytearray)):
        return zipfile.ZipFile(io.BytesIO(bytes(source)))
    return zipfile.ZipFile(source)


def parse_totfa_zip(source: str | os.PathLike[str] | bytes | BinaryIO) -> SubmissionParseResult:
    """解析 TOTFA.zip（路徑、bytes 或檔案物件皆可）內的 TOTFA.xml。

    Args:
        source: 上傳的 zip 內容。

    Returns:
        SubmissionParseResult（與 `parse_submission_xml` 同形狀）。

    Raises:
        SubmissionXmlError: zip 無法開啟、找不到或有多份 TOTFA.xml、
            XML 超過大小上限，或 XML 本身解析失敗。
    """
    try:
        with _open_zip(source) as zf:
            members = [
                info
                for info in zf.infolist()
                if not info.is_dir()
                and PurePosixPath(info.filename).name.upper() == TOTFA_XML_NAME.upper()
            ]
            if not members:
                raise SubmissionXmlError(f"壓縮檔內找不到 {TOTFA_XML_NAME}")
            if len(members) > 1:
                raise SubmissionXmlError(f"壓縮檔內含多份 {TOTFA_XML_NAME}，無法判定")
            info = members[0]
            if info.file_size > MAX_TOTFA_XML_BYTES:
                raise SubmissionXmlError(
                    f"{TOTFA_XML_NAME} 解壓後大小 {info.file_size} 超過上限 {MAX_TOTFA_XML_BYTES}"
                )
            with zf.open(info) as member:
                data = member.read(MAX_TOTFA_XML_BYTES + 1)
    except (zipfile.BadZipFile, OSError, RuntimeError, NotImplementedError) as exc:
        raise SubmissionXmlError(f"TOTFA 壓縮檔無法讀取：{exc}") from exc

    if len(data) > MAX_TOTFA_XML_BYTES:
        raise SubmissionXmlError(f"{TOTFA_XML_NAME} 超過大小上限 {MAX_TOTFA_XML_BYTES}")
    return parse_submission_xml_bytes(data)


# ── 批次 ──────────────────────────────────────────────────────────


def batch_name_from_header(header: dict[str, str]) -> str:
    """由 tdata 推得批次名 `MONTHLY-YYYYMM`（t3 費用年月，民國年）。

    Raises:
        SubmissionXmlError: t3 缺漏或格式不符（民國 YYYMM、月份 01–12）。
    """
    t3 = (header.get("t3") or "").strip()
    match = _ROC_YEAR_MONTH_RE.match(t3)
    if match is None:
        raise SubmissionXmlError(f"tdata.t3（費用年月）無法解析：{t3!r}")
    year = int(match.group(1)) + ROC_OFFSET
    month = int(match.group(2))
    if not 1 <= month <= 12:
        raise SubmissionXmlError(f"tdata.t3（費用年月）月份超出範圍：{t3!r}")
    return f"{BATCH_PREFIX}{year:04d}{month:02d}"


# ── 篩選 ──────────────────────────────────────────────────────────


def _as_decimal(value: str | None) -> Decimal | None:
    """數值字串 → Decimal；缺漏、空白、非數字或非有限值一律回 None。"""
    if value is None or not value.strip():
        return None
    try:
        number = Decimal(value.strip())
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def orders_over_points(
    case: SubmissionCase, threshold: Decimal = ORDER_POINTS_THRESHOLD
) -> tuple[OrderRecord, ...]:
    """回傳點數（p12）嚴格大於門檻的醫令；點數缺漏者不列入。"""
    flagged: list[OrderRecord] = []
    for order in case.orders:
        points = _as_decimal(order.points)
        if points is not None and points > threshold:
            flagged.append(order)
    return tuple(flagged)


def declared_amount(order: OrderRecord) -> Decimal | None:
    """申報金額排序鍵：優先 p12 點數，缺漏時退回 p11 單價；皆缺回 None。"""
    points = _as_decimal(order.points)
    if points is not None:
        return points
    return _as_decimal(order.unit_price)


def is_points_over(order: OrderRecord, threshold: Decimal = ORDER_POINTS_THRESHOLD) -> bool:
    """單一醫令點數（p12）是否嚴格大於門檻；點數缺漏視為未超標。"""
    points = _as_decimal(order.points)
    return points is not None and points > threshold


def is_drug_over_price(order: OrderRecord, threshold: Decimal = DRUG_UNIT_PRICE_THRESHOLD) -> bool:
    """藥品行（p3＝DRUG_CATEGORY）單價（p11）是否嚴格大於門檻。非藥品恆為 False。"""
    if order.category != DRUG_CATEGORY:
        return False
    price = _as_decimal(order.unit_price)
    return price is not None and price > threshold


def is_drug_unpriced(order: OrderRecord) -> bool:
    """藥品行單價缺漏或為 0（無法以單價門檻判定，須另行核對）。非藥品恆為 False。

    TOTFA.xml 實測藥品行 p11 皆為 0.00，因此單價門檻目前無法對藥品判定；
    呼叫端應揭露此數量，而非把它當成「未超標」。
    """
    if order.category != DRUG_CATEGORY:
        return False
    price = _as_decimal(order.unit_price)
    return price is None or price == 0


def drugs_over_unit_price(
    case: SubmissionCase, threshold: Decimal = DRUG_UNIT_PRICE_THRESHOLD
) -> tuple[OrderRecord, ...]:
    """回傳藥品行單價嚴格大於門檻者（逐行謂詞 `is_drug_over_price` 的案件層包裝）。"""
    return tuple(o for o in case.orders if is_drug_over_price(o, threshold))


def unpriced_drug_orders(case: SubmissionCase) -> tuple[OrderRecord, ...]:
    """藥品行單價缺漏或為 0 者（逐行謂詞 `is_drug_unpriced` 的案件層包裝）。"""
    return tuple(o for o in case.orders if is_drug_unpriced(o))


# ── 案件 ID（內容雜湊） ─────────────────────────────────────────────


def _content_key(batch: str, case: SubmissionCase) -> str:
    """批次＋案件 dhead/dbody/pdata 原文的 canonical JSON 雜湊（不含順序序號）。

    `raw` 含 d49 姓名，但只餵入雜湊、不寫入任何日誌。
    """
    body = {
        "batch": batch,
        "raw": dict(sorted(case.raw.items())),
        "orders": [dict(sorted(order.raw.items())) for order in case.orders],
    }
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def monthly_case_ids(batch: str, cases: Sequence[SubmissionCase]) -> tuple[str, ...]:
    """為批次內每筆案件產生穩定的 `MON-…` 內容雜湊 ID（與 cases 同順序）。

    同一內容第 n 次出現（n 從 0 起算）以序號混入雜湊，故完全相同的兩筆
    真實申報列仍得到不同 ID；重匯入同一檔案時序號不變，結果冪等。
    """
    seen: Counter[str] = Counter()
    ids: list[str] = []
    for case in cases:
        key = _content_key(batch, case)
        occurrence = seen[key]
        seen[key] += 1
        digest = hashlib.sha256(f"{key}:{occurrence}".encode()).hexdigest()
        ids.append(f"{CASE_ID_PREFIX}{digest[:32]}")
    return tuple(ids)
