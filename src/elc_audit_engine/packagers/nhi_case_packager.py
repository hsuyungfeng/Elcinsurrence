"""健保標準送審檔案打包器（Phase 21-01）。

規格依據：電子抽審.md §二（檔案格式與命名）。
- 檔名：第一階層代碼（2 碼）＋第二階層代碼（1 碼）＋案件分類代碼（2 碼）＋案件流水號（6 碼）；
  同一案件有多個檔案時，末尾加數字編號區隔（如 13B190123451、13B190123452）。
- 格式：嚴禁 ZIP、RAR、EXE；白名單為 JPG、JPEG、PNG、BMP、TIFF、PDF、TXT。
  DICOM 需 DICOMDIR 引導檔，本模組尚未支援，故 .dcm 一律拒收並說明原因。
- 單案一次性送審：同一案件的全部檔案與 XML 放在同一個送審資料夾（以 ZIP 包裝供下載），禁止分拆。

注意：此處的 ZIP 是「送審資料夾的下載容器」，與規格禁止上傳的壓縮檔不同；送審時由地端 Agent
將資料夾內的檔案逐一上傳，不會把 ZIP 本身送出。
"""

from __future__ import annotations

import io
import os
import re
import zipfile

ALLOWED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".pdf", ".txt"})
BLOCKED_EXTENSIONS = frozenset({".zip", ".rar", ".exe"})

_STAGE1_RE = re.compile(r"^\d{2}$")
_STAGE2_RE = re.compile(r"^[A-Z]$")
_CASE_CLASS_RE = re.compile(r"^\d{1,2}$")
_CASE_SEQ_RE = re.compile(r"^\d{1,6}$")


class PackagerError(ValueError):
    """送審打包無法進行（代碼格式錯誤、缺少必要資料）。"""


def build_base_name(stage1: str, stage2: str, case_class: str, case_seq: str) -> str:
    """組出 11 碼基礎檔名：第一階 2 碼＋第二階 1 碼＋案件分類 2 碼＋流水號 6 碼。

    案件分類不足 2 碼時左補 0；流水號不足 6 碼時左補 0（規格為定寬欄位）。
    """
    if not _STAGE1_RE.match(stage1 or ""):
        raise PackagerError("第一階層代碼須為 2 碼數字")
    if not _STAGE2_RE.match(stage2 or ""):
        raise PackagerError("第二階層代碼須為 1 碼大寫英文字母")
    if not _CASE_CLASS_RE.match(str(case_class or "")):
        raise PackagerError("案件分類代碼須為 1～2 碼數字")
    if not _CASE_SEQ_RE.match(str(case_seq or "")):
        raise PackagerError("案件流水號須為 1～6 碼數字")
    return f"{stage1}{stage2}{int(case_class):02d}{int(case_seq):06d}"


def check_extension(filename: str) -> str:
    """回傳小寫副檔名；禁止格式與非白名單格式拋出 PackagerError（附原因）。"""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in BLOCKED_EXTENSIONS:
        raise PackagerError(f"禁止上傳的格式：{ext}（規格嚴禁 ZIP、RAR、EXE）")
    if ext == ".dcm":
        raise PackagerError("DICOM 尚未支援（需以 DICOMDIR 為引導檔），請改以 JPG 等圖檔送審")
    if ext not in ALLOWED_EXTENSIONS:
        raise PackagerError(f"非白名單格式：{ext or '（無副檔名）'}")
    return ext


def plan_evidence_names(base_name: str, filenames: list[str]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """規劃送審檔名。回傳 (接受的 [(原檔名, 新檔名)], 拒收的 [(原檔名, 原因)])。

    同一案件僅一個接受檔案時使用基礎檔名；多個檔案時依序加上數字編號 1, 2, ...，避免覆蓋。
    """
    accepted_raw: list[tuple[str, str]] = []
    rejected: list[tuple[str, str]] = []
    for name in filenames:
        try:
            ext = check_extension(name)
        except PackagerError as exc:
            rejected.append((name, str(exc)))
            continue
        accepted_raw.append((name, ext))

    if len(accepted_raw) == 1:
        new_names = [f"{base_name}{accepted_raw[0][1]}"]
    else:
        new_names = [f"{base_name}{index}{ext}" for index, (_, ext) in enumerate(accepted_raw, start=1)]
    accepted = [(original, new) for (original, _), new in zip(accepted_raw, new_names)]
    return accepted, rejected


def build_case_package(
    *,
    base_name: str,
    xml_bytes: bytes,
    evidence: list[tuple[str, bytes]],
) -> tuple[bytes, dict]:
    """組裝單案送審資料夾（ZIP 容器），回傳 (ZIP 位元組, 打包報告)。

    ZIP 結構：<base>/<base>.xml 為送審 XML；<base>/<新檔名> 為接受的佐證檔；
    <base>/MANIFEST.txt 記錄原檔名→送審檔名對照與被拒收的檔案及原因。
    """
    accepted, rejected = plan_evidence_names(base_name, [name for name, _ in evidence])
    data_by_name = dict(evidence)
    manifest_lines = [f"送審基礎檔名：{base_name}", f"XML：{base_name}.xml"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{base_name}/{base_name}.xml", xml_bytes)
        for original, new_name in accepted:
            archive.writestr(f"{base_name}/{new_name}", data_by_name[original])
            manifest_lines.append(f"{new_name}  ← {original}")
        for original, reason in rejected:
            manifest_lines.append(f"[拒收] {original}：{reason}")
        archive.writestr(f"{base_name}/MANIFEST.txt", "\n".join(manifest_lines) + "\n")
    report = {
        "base_name": base_name,
        "xml_file": f"{base_name}.xml",
        "accepted": [{"original": o, "submitted_as": n} for o, n in accepted],
        "rejected": [{"original": o, "reason": r} for o, r in rejected],
    }
    return buffer.getvalue(), report


__all__ = [
    "ALLOWED_EXTENSIONS",
    "BLOCKED_EXTENSIONS",
    "PackagerError",
    "build_base_name",
    "build_case_package",
    "check_extension",
    "plan_evidence_names",
]
