"""LibreOffice headless `.doc` -> `.docx` 批次轉換。

不使用任何雲端服務：呼叫本機安裝的 LibreOffice (`soffice --headless`)
將舊版二進位 `.doc` 檔案轉換為可被 python-docx 讀取的 OOXML `.docx` 檔案。

環境探測注意：`soffice --version` 成功不代表 headless 轉檔可用 —— 在
沙箱／容器等受限環境中，soffice 可能正常回報版本，但轉檔因 profile／
dconf 寫入權限問題而直接失敗（exit 非 0）。因此本模組提供
`soffice_is_functional()` 做「真實轉檔探測」，測試與建置流程都應以它
為準，而不是 `shutil.which` 或 `--version`。
"""

import glob
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _build_convert_cmd(
    profile_dir: str,
    outdir: str,
    convert_to: str,
    source_path: str,
) -> list[str]:
    """組出 headless 轉檔指令。

    `-env:UserInstallation` 將 LibreOffice profile 導向可寫目錄，避免污染
    使用者 `~/.config/libreoffice`，也避免唯讀 HOME 環境（沙箱/CI）下
    profile 寫入失敗導致整批轉檔 exit 1。`--norestore`／`--nolockcheck`
    避免舊 session 恢復與 profile 鎖定干擾批次轉檔。
    """
    return [
        "soffice",
        f"-env:UserInstallation={Path(profile_dir).as_uri()}",
        "--headless",
        "--norestore",
        "--nolockcheck",
        "--convert-to",
        convert_to,
        "--outdir",
        outdir,
        source_path,
    ]


def soffice_is_functional() -> bool:
    """真實轉檔探測：以一個最小的 .docx 轉 PDF，驗證 headless 轉檔路徑可用。

    Args:
        無。

    Returns:
        `True` 當且僅當 soffice 存在、且實際完成一次最小轉檔並產出檔案。
        任何失敗（PATH 找不到、超時、exit 非 0、輸出檔不存在）都回傳
        `False` —— 呼叫端（如測試的 skip 條件）據此判斷環境是否可用，
        避免「`--version` 成功但轉檔必失敗」的誤判。
    """
    if shutil.which("soffice") is None:
        return False
    try:
        import docx as _docx

        with tempfile.TemporaryDirectory(prefix="elc_soffice_probe_") as tmp:
            source_path = os.path.join(tmp, "probe.docx")
            outdir = os.path.join(tmp, "out")
            profile_dir = os.path.join(tmp, "prof")
            os.makedirs(outdir, exist_ok=True)

            document = _docx.Document()
            document.add_paragraph("soffice probe")
            document.save(source_path)

            result = subprocess.run(
                _build_convert_cmd(profile_dir, outdir, "pdf", source_path),
                capture_output=True,
                timeout=60,
            )
            if result.returncode != 0:
                return False
            return os.path.isfile(os.path.join(outdir, "probe.pdf"))
    except (subprocess.TimeoutExpired, OSError, ImportError):
        return False


def convert_doc_files(source_dir: str, staging_dir: str) -> list[str]:
    """將 `source_dir` 內所有 `.doc`（排除 `.docx`）轉換為 `.docx`，輸出至 `staging_dir`。

    Args:
        source_dir: 來源文件目錄（可能同時包含 .doc 與 .docx）。
        staging_dir: 轉換後 .docx 輸出目錄，若不存在會自動建立。

    Returns:
        轉換完成的 .docx 檔案完整路徑清單（於 staging_dir 內）。

    Raises:
        RuntimeError: 若本機找不到 `soffice`（LibreOffice）執行檔。
        subprocess.CalledProcessError: 若轉換過程中 soffice 回傳非 0。
        subprocess.TimeoutExpired: 若單一檔案轉換超過 120 秒。
    """
    os.makedirs(staging_dir, exist_ok=True)
    # 把 LibreOffice profile 放在 staging 內：正式流程（data/converted_docx）
    # 重跑時可覆用，測試用 tmp_path 時自動隔離，不污染使用者 HOME。
    profile_dir = os.path.join(staging_dir, ".lo_profile")
    os.makedirs(profile_dir, exist_ok=True)

    doc_paths = sorted(
        p
        for p in glob.glob(os.path.join(source_dir, "*.doc"))
        if not p.lower().endswith(".docx")
    )

    converted_paths = []
    for doc_path in doc_paths:
        try:
            subprocess.run(
                _build_convert_cmd(profile_dir, staging_dir, "docx", doc_path),
                check=True,
                capture_output=True,
                timeout=120,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "soffice (LibreOffice) not found on PATH — required for .doc conversion"
            ) from exc

        base_name = os.path.splitext(os.path.basename(doc_path))[0]
        converted_path = os.path.join(staging_dir, f"{base_name}.docx")
        converted_paths.append(converted_path)

    return converted_paths
