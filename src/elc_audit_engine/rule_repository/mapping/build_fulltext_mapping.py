"""零 LLM 確定性官方完整給付規定條文建置器（Phase 38）。

設計原則（AGENTs.md 硬不變量）：
- **100% 確定性原文擷取**：絕不呼叫 LLM、絕不捏造、絕不截斷官方條文。
- **納入來源（純 Python 標準庫，零 LibreOffice 依賴）**：
  1. 本機官方藥品給付規定 `.odt`（如 `完整給付規定1140221.odt`）× 藥品 CSV `給付規定章節` 欄；
  2. 本機官方 `.docx`（`officialdocument/審查注意事項/*.docx`，含各科西醫基層審查注意事項與手術節支付標準）；
  3. 給付項目 CSV 官方 `備註` 欄（如 `261119`）。
- **防洗空與優先序**：
  - 寫入 `rule_mapping` 時標記 `article_source = "official_fulltext"` 與確定性 `source_version`；
  - 絕不執行整表 `DELETE FROM rule_mapping`；未命中代碼維持既有列不動；
  - 若 `official_docs_dir` 缺失或無 `.odt`/`.docx`，保留既有 `official_fulltext` 列不被降級覆寫；
  - 僅在 `prune_orphans=True`（對應 `replace=True`）時清除兩主表皆已不存在的孤立列。

用法：
    uv run python -m elc_audit_engine.rule_repository.mapping.build_fulltext_mapping
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import settings
from elc_audit_engine.rule_repository import db as rule_db
from elc_audit_engine.rule_repository.loaders._csv_table import PLACEHOLDER_TEXTS

OFFICIAL_ARTICLE_SOURCE = "official_fulltext"

_ODT_NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
}
_DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

# 嚴格匹配健保藥品給付規定章節（例如 `1.2.1.`、`1.3.2.6 `、`7.1.`），排除 `2.18歲`、`0.5mg` 等內文數值
_ODT_CHAPTER_RE = re.compile(r"^(\d+(?:\.\d+)+)(?:\.|(?=\s))")
_ODT_FALSE_UNIT_RE = re.compile(
    r"^\d+(?:\.\d+)+\s*(?:mg|g|ml|mcg|ug|iu|%|歲|年|月|日|天|次|週|小時|分鐘)\b",
    re.IGNORECASE,
)
_CSV_CHAPTER_TOKEN_RE = re.compile(r"\d+(?:\.\d+)+")

# 健保診療項目代碼（5 碼數字 + 1 碼大寫英文字母，支援中文緊鄰）
_PROC_CODE_RE = re.compile(r"(?<![A-Za-z0-9])(\d{5}[A-Z])(?![A-Za-z0-9])")
_EXACT_PROC_CODE_RE = re.compile(r"^\d{5}[A-Z]$")

# 審查注意事項頂層項次與大標題
_DOCX_MAJOR_HEAD_RE = re.compile(r"^[一二三四五六七八九十]+、")
_DOCX_ITEM_HEAD_RE = re.compile(r"^[（(]([一二三四五六七八九十百]+)[）)]")
_DOCX_TABLE_NOTE_KEYWORDS = ("註", "限制", "限", "不得", "規定", "申報", "包括", "附")

# 行程內唯讀語料快取：key = (resolved_dir, files_fingerprint)
_CORPUS_CACHE: dict[
    tuple[str, tuple[tuple[str, int, int], ...]],
    tuple[dict[str, str], str | None, dict[str, list[tuple[str, str]]]],
] = {}


@dataclass(frozen=True)
class FulltextBuildStats:
    """一次官方全文建置之統計結果（零 PHI）。"""

    db_path: str
    official_docs_dir: str
    official_docs_available: bool
    odt_file: str | None
    odt_chapters: int
    docx_files: int
    drug_mapped: int
    payment_mapped: int
    total_written: int
    orphans_pruned: int
    rule_mapping_rows: int
    source_version: str
    elapsed_seconds: float
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "official_docs_available": self.official_docs_available,
            "odt_file": self.odt_file,
            "odt_chapters": self.odt_chapters,
            "docx_files": self.docx_files,
            "drug_mapped": self.drug_mapped,
            "payment_mapped": self.payment_mapped,
            "total_written": self.total_written,
            "orphans_pruned": self.orphans_pruned,
            "rule_mapping_rows": self.rule_mapping_rows,
            "source_version": self.source_version,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "warnings": list(self.warnings),
        }


def _norm_dedup_key(text: str) -> str:
    return re.sub(r"[\s。；;，,：:（）()]+", "", text or "")


def _is_placeholder(text: str | None) -> bool:
    s = (text or "").strip()
    return not s or s.lower() in PLACEHOLDER_TEXTS


def _iter_odt_blocks(parent: ET.Element) -> list[str]:
    """依文件順序抽取 ODT 段落、標題與表格文字（表格以 ` | ` 串接每列保留）。"""
    blocks: list[str] = []
    for elem in parent:
        tag = elem.tag.split("}")[-1]
        if tag in ("p", "h"):
            t = "".join(elem.itertext()).strip()
            if t:
                blocks.append(t)
        elif tag == "table":
            rows_txt: list[str] = []
            for tr in elem.findall(".//table:table-row", _ODT_NS):
                cells = [
                    " ".join("".join(tc.itertext()).split())
                    for tc in tr.findall("table:table-cell", _ODT_NS)
                ]
                if any(cells):
                    rows_txt.append(" | ".join(cells))
            if rows_txt:
                blocks.append("\n".join(rows_txt))
        elif tag in ("section", "list", "list-item"):
            blocks.extend(_iter_odt_blocks(elem))
        else:
            t = "".join(elem.itertext()).strip()
            if t:
                blocks.append(t)
    return blocks


def _is_valid_odt_chapter_heading(line: str) -> str | None:
    """判定是否為合法健保藥品給付規定章節標題；符合回傳正規化章節碼（無尾點），否則 None。"""
    s = line.strip()
    if not s or _ODT_FALSE_UNIT_RE.match(s):
        return None
    m = _ODT_CHAPTER_RE.match(s)
    if not m:
        return None
    ch_num = m.group(1).rstrip(".")
    parts = ch_num.split(".")
    if len(parts) < 2:
        return None
    try:
        top = int(parts[0])
    except ValueError:
        return None
    if not (1 <= top <= 15):
        return None
    # 排除像 `1.0` 版本號或純小數數值（後無文字且僅 2 段且次段為 0）
    if len(parts) == 2 and parts[1] == "0":
        return None
    return ch_num


def parse_odt_drug_chapters(odt_path: str | Path) -> dict[str, str]:
    """解析健保官方藥品完整給付規定 `.odt`，回傳 `{章節碼(無尾點): 完整原文}`。

    若同一章節碼同時出現在目錄與內文，自動保留內容最長之內文區段。
    """
    path = Path(odt_path)
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("content.xml"))
    body = root.find(".//office:text", _ODT_NS)
    if body is None:
        return {}
    blocks = _iter_odt_blocks(body)

    candidates: dict[str, list[str]] = defaultdict(list)
    cur_ch: str | None = None
    cur_lines: list[str] = []

    def _flush() -> None:
        if cur_ch and cur_lines:
            candidates[cur_ch].append("\n".join(cur_lines).strip())

    for blk in blocks:
        ch = _is_valid_odt_chapter_heading(blk)
        if ch is not None:
            _flush()
            cur_ch = ch
            cur_lines = [blk]
        elif cur_ch is not None:
            # 遇到下一個大節（例如 `第2節 ...`）時結束當前章節，避免把下一節標題吸進上一節尾端
            if re.match(r"^第\s*\d+\s*節\b", blk):
                _flush()
                cur_ch = None
                cur_lines = []
            else:
                cur_lines.append(blk)
    _flush()

    result: dict[str, str] = {}
    for ch, texts in candidates.items():
        best = max(texts, key=len)
        if best:
            result[ch] = best
    return result


def _chapter_sort_key(ch: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in ch.split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return tuple(out)


def lookup_odt_chapter(chapters: dict[str, str], chapter_code: str) -> str | None:
    """依章節碼查詢完整原文；若指向父章節且無獨立段落，自動依序彙整全部直屬子節。"""
    norm = chapter_code.strip().rstrip(".")
    if not norm:
        return None
    if norm in chapters:
        return chapters[norm]
    prefix = norm + "."
    sub_keys = sorted((k for k in chapters if k.startswith(prefix)), key=_chapter_sort_key)
    if sub_keys:
        return "\n\n".join(chapters[k] for k in sub_keys)
    return None


def _extract_docx_code_articles(docx_path: Path) -> dict[str, list[tuple[str, str]]]:
    """解析單一官方 `.docx`（同時涵蓋審查注意事項跨段落區塊與支付標準表格註記）。"""
    fname = docx_path.name
    hits: dict[str, list[tuple[str, str]]] = defaultdict(list)

    with zipfile.ZipFile(docx_path) as zf:
        if "word/document.xml" not in zf.namelist():
            return hits
        root = ET.fromstring(zf.read("word/document.xml"))

    body = root.find("w:body", _DOCX_NS)
    if body is None:
        return hits

    # 1. 表格列（如 2-2-7 手術節支付標準：首欄醫令碼，其餘欄含項目名稱與註記）
    for tbl in body.findall(".//w:tbl", _DOCX_NS):
        for tr in tbl.findall(".//w:tr", _DOCX_NS):
            cells = ["".join(tc.itertext()).strip() for tc in tr.findall("w:tc", _DOCX_NS)]
            if len(cells) < 2:
                continue
            first_code = cells[0].strip().upper()
            if not _EXACT_PROC_CODE_RE.match(first_code):
                continue
            desc = " ".join(c for c in cells[1:] if c and c.lower() != "v").strip()
            if not desc:
                continue
            if any(kw in desc for kw in _DOCX_TABLE_NOTE_KEYWORDS):
                loc = f"{fname}（支付標準表）"
                hits[first_code].append((loc, f"{first_code} {desc}"))

    # 2. 表格外段落（審查注意事項跨段落完整條文分組）
    cur_major: str | None = None
    cur_item_label: str | None = None
    cur_lines: list[str] = []

    def _flush_item() -> None:
        if not cur_lines:
            return
        block_text = "\n".join(cur_lines).strip()
        codes = sorted(set(_PROC_CODE_RE.findall(block_text)))
        if not codes:
            return
        loc_parts = [fname]
        if cur_major:
            loc_parts.append(cur_major[:24])
        if cur_item_label:
            loc_parts.append(cur_item_label)
        loc = " > ".join(loc_parts)
        for code in codes:
            hits[code].append((loc, block_text))

    for child in body:
        tag = child.tag.split("}")[-1]
        if tag != "p":
            if tag == "tbl":
                _flush_item()
                cur_item_label = None
                cur_lines = []
            continue
        text = "".join(child.itertext()).strip()
        if not text:
            continue
        if _DOCX_MAJOR_HEAD_RE.match(text):
            _flush_item()
            cur_major = text
            cur_item_label = None
            cur_lines = []
            continue
        item_m = _DOCX_ITEM_HEAD_RE.match(text)
        if item_m:
            _flush_item()
            cur_item_label = f"({item_m.group(1)})"
            cur_lines = [text]
            continue
        if cur_item_label is not None:
            cur_lines.append(text)
        else:
            # 獨立段落（無 `(一)` 編號前綴但內含醫令碼，如一般原則條文）
            codes = sorted(set(_PROC_CODE_RE.findall(text)))
            if codes:
                loc = f"{fname} > {cur_major[:24]}" if cur_major else fname
                for code in codes:
                    hits[code].append((loc, text))

    _flush_item()
    return hits


def _discover_official_files(official_docs_dir: Path) -> tuple[Path | None, list[Path]]:
    if not official_docs_dir.is_dir():
        return None, []
    odts = sorted(official_docs_dir.glob("*完整給付規定*.odt"))
    if not odts:
        odts = sorted(official_docs_dir.glob("*.odt"))
    odt_path = odts[-1] if odts else None
    docx_files = sorted(official_docs_dir.glob("*.docx"))
    return odt_path, docx_files


def _load_official_corpus_cached(
    official_docs_dir: Path,
    *,
    need_odt: bool,
    need_docx: bool,
) -> tuple[dict[str, str], str | None, dict[str, list[tuple[str, str]]], list[tuple[str, int, int]]]:
    """載入並依 (檔名, mtime_ns, size) 快取本機官方 ODT 與 DOCX 解析結果。"""
    odt_path, docx_files = _discover_official_files(official_docs_dir)
    all_files: list[Path] = []
    if odt_path is not None:
        all_files.append(odt_path)
    all_files.extend(docx_files)

    fingerprint: list[tuple[str, int, int]] = []
    for f in all_files:
        try:
            st = f.stat()
            fingerprint.append((f.name, st.st_mtime_ns, st.st_size))
        except OSError:
            continue

    if not need_odt and not need_docx:
        return {}, (odt_path.name if odt_path else None), {}, fingerprint

    cache_key = (str(official_docs_dir.resolve()), tuple(fingerprint))
    cached = _CORPUS_CACHE.get(cache_key)
    if cached is not None:
        chapters, odt_name, docx_index = cached
        # 若快取先前僅載入部分，按需補齊
        if (not need_odt or chapters or odt_path is None) and (not need_docx or docx_index or not docx_files):
            return chapters, odt_name, docx_index, fingerprint

    chapters = cached[0] if cached is not None else {}
    odt_name = odt_path.name if odt_path else None
    docx_index: dict[str, list[tuple[str, str]]] = (
        cached[2] if cached is not None else defaultdict(list)
    )

    if need_odt and odt_path is not None and not chapters:
        chapters = parse_odt_drug_chapters(odt_path)

    if need_docx and docx_files and not docx_index:
        merged: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for df in docx_files:
            for code, items in _extract_docx_code_articles(df).items():
                merged[code].extend(items)
        docx_index = merged

    _CORPUS_CACHE[cache_key] = (chapters, odt_name, docx_index)
    return chapters, odt_name, docx_index, fingerprint


def _read_drug_chapters_csv(drug_csv_path: str | Path | None) -> dict[str, list[str]]:
    """從藥品 CSV 讀取 `{藥品代號: [章節碼, ...]}`；缺檔或缺 `給付規定章節` 欄時回傳空 dict。"""
    if not drug_csv_path or not os.path.isfile(drug_csv_path):
        return {}
    mapping: dict[str, list[str]] = {}
    with open(drug_csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "給付規定章節" not in reader.fieldnames or "藥品代號" not in reader.fieldnames:
            return {}
        for row in reader:
            code = (row.get("藥品代號") or "").strip().upper()
            raw_ch = (row.get("給付規定章節") or "").strip()
            if not code or not raw_ch:
                continue
            tokens = [t.rstrip(".") for t in _CSV_CHAPTER_TOKEN_RE.findall(raw_ch)]
            if tokens:
                # 去重保序
                seen: set[str] = set()
                ordered = [t for t in tokens if not (t in seen or seen.add(t))]
                mapping[code] = ordered
    return mapping


def _read_payment_notes_csv(payment_csv_path: str | Path | None) -> tuple[str | None, dict[str, str]]:
    """從給付項目 CSV 讀取 `{診療項目代碼: 官方備註}`；缺檔或缺 `備註` 欄時回傳空 dict。"""
    if not payment_csv_path or not os.path.isfile(payment_csv_path):
        return None, {}
    notes: dict[str, str] = {}
    csv_name = os.path.basename(str(payment_csv_path))
    with open(payment_csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "備註" not in reader.fieldnames or "診療項目代碼" not in reader.fieldnames:
            return csv_name, {}
        for row in reader:
            code = (row.get("診療項目代碼") or "").strip().upper()
            note = (row.get("備註") or "").strip()
            if code and not _is_placeholder(note):
                notes[code] = note
    return csv_name, notes


def _compute_source_version(
    official_fp: list[tuple[str, int, int]],
    payment_csv_path: str | Path | None,
    drug_csv_path: str | Path | None,
) -> str:
    h = hashlib.sha256()
    for name, mtime_ns, size in official_fp:
        h.update(f"doc:{name}:{mtime_ns}:{size}\n".encode("utf-8"))
    for tag, path in (("pay", payment_csv_path), ("drug", drug_csv_path)):
        if path and os.path.isfile(path):
            st = os.stat(path)
            h.update(f"{tag}:{os.path.basename(str(path))}:{st.st_mtime_ns}:{st.st_size}\n".encode("utf-8"))
    return f"official-v1:{h.hexdigest()[:12]}"


def _dedup_and_format_sections(sections: list[tuple[str, str]]) -> tuple[str, str]:
    """依序去重並組裝 `(article_location, article_full_text)`。"""
    locs: list[str] = []
    seen_locs: set[str] = set()
    kept_keys: list[str] = []
    rendered_parts: list[str] = []

    for loc, text in sections:
        clean_text = (text or "").strip()
        if not clean_text:
            continue
        key = _norm_dedup_key(clean_text)
        if not key:
            continue
        # 若該段完整內容已被先前較完整的官方條文包含，跳過避免重複列印
        if any(key in existing for existing in kept_keys):
            continue
        kept_keys.append(key)
        if loc not in seen_locs:
            seen_locs.add(loc)
            locs.append(loc)
        rendered_parts.append(f"【{loc}】\n{clean_text}")

    return "; ".join(locs), "\n\n".join(rendered_parts)


def build_fulltext_mapping(
    db_path: str | Path,
    *,
    payment_csv_path: str | Path | None = None,
    drug_csv_path: str | Path | None = None,
    official_docs_dir: str | Path | None = None,
    prune_orphans: bool = False,
) -> FulltextBuildStats:
    """以純確定性方式從本機官方 ODT/DOCX 與 CSV 備註建置 `rule_mapping` 完整條文。

    嚴守防洗空契約：
    - 絕不執行整表 `DELETE FROM rule_mapping`；
    - 若 `official_docs_dir` 不存在或無官方檔，保留既有 `article_source='official_fulltext'` 列；
    - 僅在 `prune_orphans=True` 時刪除兩張主表皆已不存在的孤立列。
    """
    t0 = time.monotonic()
    resolved_docs = Path(official_docs_dir) if official_docs_dir is not None else Path(settings.RULE_SOURCE_DIR)
    warnings_list: list[str] = []

    conn = rule_db.get_connection(str(db_path))
    try:
        rule_db.init_schema(conn)
        payment_codes = {r[0] for r in conn.execute("SELECT code FROM payment_rules")}
        drug_codes = {r[0] for r in conn.execute("SELECT code FROM drug_rules")}
        existing_official_codes = {
            r[0]
            for r in conn.execute(
                "SELECT code FROM rule_mapping WHERE article_source = ?",
                (OFFICIAL_ARTICLE_SOURCE,),
            )
        }

        drug_chapter_map = _read_drug_chapters_csv(drug_csv_path)
        payment_csv_name, payment_notes_map = _read_payment_notes_csv(payment_csv_path)

        # 僅在實際需要時才解析 ODT / DOCX（隔離測試若只有合成短代碼則 0 ms 跳過）
        need_odt = any(c in drug_codes for c in drug_chapter_map)
        need_docx = any(_EXACT_PROC_CODE_RE.match(c) for c in payment_codes)

        odt_path, docx_files = _discover_official_files(resolved_docs)
        official_docs_available = bool(odt_path is not None or docx_files)
        if not official_docs_available:
            warnings_list.append(
                f"官方條文目錄不存在或無 .odt/.docx（{resolved_docs.name}），已保留既有 official_fulltext 列不覆寫。"
            )

        chapters, odt_name, docx_index, official_fp = _load_official_corpus_cached(
            resolved_docs,
            need_odt=need_odt,
            need_docx=need_docx,
        )
        source_version = _compute_source_version(official_fp, payment_csv_path, drug_csv_path)

        to_upsert: list[tuple[str, str, str, str, str]] = []
        drug_mapped = 0
        payment_mapped = 0

        # 1. 藥品完整條文（ODT 章節對應）
        if chapters and odt_name:
            for code in sorted(drug_codes):
                ch_list = drug_chapter_map.get(code)
                if not ch_list:
                    continue
                sections: list[tuple[str, str]] = []
                for ch in ch_list:
                    full_text = lookup_odt_chapter(chapters, ch)
                    if full_text:
                        sections.append((f"健保藥品給付規定原文｜{odt_name}｜章節 {ch}", full_text))
                if sections:
                    loc, full = _dedup_and_format_sections(sections)
                    if full:
                        to_upsert.append((code, loc, full, OFFICIAL_ARTICLE_SOURCE, source_version))
                        drug_mapped += 1

        # 2. 診療項目完整條文（21 份 .docx 審查注意事項＋支付標準表＋CSV 備註）
        for code in sorted(payment_codes):
            # 若官方目錄不可用且該碼已有 official_fulltext 列，保留原列不降級覆寫
            if not official_docs_available and code in existing_official_codes:
                continue

            sections = []
            for loc, txt in docx_index.get(code, ()):
                sections.append((loc, txt))

            note = payment_notes_map.get(code)
            if note and payment_csv_name:
                sections.append((f"健保支付標準官方備註｜{payment_csv_name}", note))

            if sections:
                loc, full = _dedup_and_format_sections(sections)
                if full:
                    to_upsert.append((code, loc, full, OFFICIAL_ARTICLE_SOURCE, source_version))
                    payment_mapped += 1

        with conn:
            if to_upsert:
                conn.executemany(
                    "INSERT OR REPLACE INTO rule_mapping "
                    "(code, article_location, article_full_text, article_source, source_version) "
                    "VALUES (?, ?, ?, ?, ?)",
                    to_upsert,
                )

            orphans_pruned = 0
            if prune_orphans:
                cur = conn.execute(
                    "DELETE FROM rule_mapping WHERE code NOT IN ("
                    "SELECT code FROM payment_rules UNION SELECT code FROM drug_rules"
                    ")"
                )
                orphans_pruned = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

        total_mapping_rows = conn.execute(
            "SELECT COUNT(*) FROM rule_mapping WHERE article_full_text IS NOT NULL AND trim(article_full_text) != ''"
        ).fetchone()[0]
    finally:
        conn.close()

    return FulltextBuildStats(
        db_path=str(db_path),
        official_docs_dir=str(resolved_docs),
        official_docs_available=official_docs_available,
        odt_file=odt_name,
        odt_chapters=len(chapters),
        docx_files=len(docx_files),
        drug_mapped=drug_mapped,
        payment_mapped=payment_mapped,
        total_written=len(to_upsert),
        orphans_pruned=orphans_pruned,
        rule_mapping_rows=total_mapping_rows,
        source_version=source_version,
        elapsed_seconds=time.monotonic() - t0,
        warnings=tuple(warnings_list),
    )


def main(argv: list[str] | None = None) -> int:
    from elc_audit_engine.rule_repository.scripts.sync_latest_rules import (
        DRUG_PATTERN,
        PAYMENT_PATTERN,
        default_db_path,
        default_rules_dir,
        pick_latest,
    )

    parser = argparse.ArgumentParser(description="零 LLM 確定性建置官方完整給付規定條文至 rule_mapping")
    parser.add_argument("--db", default=default_db_path(), help="目標 rules.sqlite3 路徑")
    parser.add_argument("--payment-csv", default=None, help="給付項目 CSV 路徑（預設取 data/rules 最新版）")
    parser.add_argument("--drug-csv", default=None, help="藥品項目 CSV 路徑（預設取 data/rules 最新版）")
    parser.add_argument("--official-docs-dir", default=None, help="官方 .odt/.docx 目錄（預設 RULE_SOURCE_DIR）")
    parser.add_argument("--prune-orphans", action="store_true", help="清理兩主表已不存在的孤立 rule_mapping 列")
    args = parser.parse_args(argv)

    rules_dir = default_rules_dir()
    payment_csv = args.payment_csv
    if payment_csv is None:
        try:
            payment_csv = pick_latest(rules_dir, PAYMENT_PATTERN)
        except FileNotFoundError:
            payment_csv = None

    drug_csv = args.drug_csv
    if drug_csv is None:
        try:
            drug_csv = pick_latest(rules_dir, DRUG_PATTERN)
        except FileNotFoundError:
            drug_csv = None

    stats = build_fulltext_mapping(
        args.db,
        payment_csv_path=payment_csv,
        drug_csv_path=drug_csv,
        official_docs_dir=args.official_docs_dir,
        prune_orphans=args.prune_orphans,
    )
    print(
        f"[build_fulltext_mapping] 藥品全文命中：{stats.drug_mapped}｜"
        f"診療項目全文命中：{stats.payment_mapped}｜"
        f"rule_mapping 總非空列：{stats.rule_mapping_rows}｜"
        f"耗時：{stats.elapsed_seconds:.2f}s｜版本：{stats.source_version}",
        file=sys.stderr,
    )
    for w in stats.warnings:
        print(f"[build_fulltext_mapping] 警告：{w}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
