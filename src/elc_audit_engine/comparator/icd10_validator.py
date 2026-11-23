"""本機 ICD-10 診斷碼合法性與語意矛盾核對器（Phase 33）。

設計原則（對應 AGENTs.md「絕對不可捏造」）：
- 僅核對並產出警告（warning），絕不擅自替換或捏造診斷碼；最終判定留給醫師。
- 查詢順序：
  1. 若環境變數 ``ELC_MEDICAL_DB_PATH`` 指向有效的本機 SQLite ``medical.db``，
     先唯讀查詢其 ICD-10 診斷表（如 ``icd10`` / ``diagnoses``）。
  2. 回退查詢專案內建 ``rule_repository.icd_titles.get_icd_chinese_title``。
- 語意矛盾偵測：針對小模型實測曾出現的高風險誤碼（例如將高尿酸 Hyperuricemia
  誤編為 E76.0 黏多醣貯積症），比對代碼所屬疾病與 A 欄鄰近文字，若出現明確
  語意衝突則回報 ``icd10_semantic_mismatch`` 警告。
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from elc_audit_engine.rule_repository.icd_titles import get_icd_chinese_title

ICD10_RE = re.compile(r"\b([A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,4})?)\b")

# 高風險誤碼規則：(正規化代碼前綴, 鄰近文字誤用特徵 regex, 建議核對說明)
_SEMANTIC_MISMATCH_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "E76",
        re.compile(r"hyperuricemia|uric\s*acid|gout|高尿酸|痛風", re.IGNORECASE),
        "E76.x 為黏多醣貯積症（Mucopolysaccharidosis），與高尿酸／痛風（常見 E79.0／M10.x）不符，請醫師核對",
    ),
    (
        "C70",
        re.compile(r"osteoarthritis|knee|constipation|headache|膝|退化|便祕|頭痛", re.IGNORECASE),
        "C70.x 為腦膜惡性腫瘤，與一般門診退化性／功能性敘述差異極大，請醫師確認是否為誤碼",
    ),
)


@dataclass(frozen=True)
class ICD10CheckResult:
    """單一 ICD-10 代碼的核對結果。"""

    code: str
    known: bool
    title_zh: str | None
    source: str
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "known": self.known,
            "title_zh": self.title_zh,
            "source": self.source,
            "warning": self.warning,
        }


def _normalize_code(code: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", (code or "").strip()).upper()


def _lookup_medical_db(code: str, db_path: str | None = None) -> str | None:
    """若本機配置了 medical.db，以唯讀模式查詢 ICD-10 名稱；不存在或查無回 None。"""
    resolved = db_path or os.environ.get("ELC_MEDICAL_DB_PATH", "").strip()
    if not resolved or not Path(resolved).is_file():
        return None
    norm = _normalize_code(code)
    dotted = code.strip().upper()
    try:
        conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error:
        return None
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        for table in ("icd10", "icd10_cm", "diagnoses"):
            if table not in tables:
                continue
            cols = {
                row[1].lower(): row[1]
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            code_col = cols.get("code") or cols.get("icd10_code") or cols.get("icd_code")
            title_col = (
                cols.get("title_zh")
                or cols.get("name_zh")
                or cols.get("chinese_name")
                or cols.get("name")
                or cols.get("description")
            )
            if not (code_col and title_col):
                continue
            row = conn.execute(
                f"SELECT {title_col} FROM {table} WHERE UPPER(REPLACE({code_col}, '.', '')) = ? OR UPPER({code_col}) = ? LIMIT 1",
                (norm, dotted),
            ).fetchone()
            if row and row[0]:
                return str(row[0]).strip()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return None


def extract_icd10_codes(text: str) -> list[str]:
    """從文字中依出現順序提取去重後的 ICD-10 代碼清單。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for m in ICD10_RE.finditer(text or ""):
        code = m.group(1).upper()
        if code not in seen:
            seen.add(code)
            ordered.append(code)
    return ordered


def validate_icd10_in_assessment(
    assessment_text: str,
    *,
    medical_db_path: str | None = None,
) -> list[ICD10CheckResult]:
    """核對 A 欄文字中的所有 ICD-10 代碼，回傳逐碼核對結果與語意警告。"""
    codes = extract_icd10_codes(assessment_text)
    results: list[ICD10CheckResult] = []
    for code in codes:
        norm = _normalize_code(code)
        title = _lookup_medical_db(code, db_path=medical_db_path)
        source = "medical_db" if title else "builtin"
        if not title:
            title = get_icd_chinese_title(code)
        known = title is not None
        if not known:
            source = "unknown"

        warning: str | None = None
        for prefix, pattern, msg in _SEMANTIC_MISMATCH_RULES:
            if norm.startswith(prefix) and pattern.search(assessment_text or ""):
                warning = msg
                break

        results.append(
            ICD10CheckResult(
                code=code,
                known=known,
                title_zh=title,
                source=source,
                warning=warning,
            )
        )
    return results
