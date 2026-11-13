"""Static AST & string scan to ensure traffic_bar contains NO audio imports and NO focus_force (D-31-01)."""

import ast
from pathlib import Path

FORBIDDEN_IMPORTS = {
    "pyaudio",
    "sounddevice",
    "wave",
    "audioop",
    "soundfile",
    "client.audio_recorder",
}


def scan_file_for_violations(file_path: Path) -> list[str]:
    violations: list[str] = []
    text = file_path.read_text(encoding="utf-8")

    # 1. AST import scan
    try:
        tree = ast.parse(text, filename=str(file_path))
    except SyntaxError as e:
        return [f"SyntaxError in {file_path}: {e}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for forbidden in FORBIDDEN_IMPORTS:
                    if alias.name == forbidden or alias.name.startswith(forbidden + "."):
                        violations.append(f"Forbidden import '{alias.name}' in {file_path}:{node.lineno}")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for forbidden in FORBIDDEN_IMPORTS:
                if mod == forbidden or mod.startswith(forbidden + "."):
                    violations.append(f"Forbidden import from '{mod}' in {file_path}:{node.lineno}")

    # 2. String scan for focus_force (excluding comment lines)
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Also strip inline comments for search
        code_part = line.split("#")[0]
        if "focus_force" in code_part:
            violations.append(f"Forbidden call 'focus_force' in {file_path}:{line_no}")

    return violations


def test_traffic_bar_static_scan_no_recording_or_focus_force():
    """確保 deploy/windows_agent/traffic_bar/ 下所有 py 檔無音訊依賴且不奪取焦點。"""
    tb_dir = Path("deploy/windows_agent/traffic_bar")
    assert tb_dir.is_dir(), f"Directory {tb_dir} must exist"

    py_files = list(tb_dir.glob("*.py"))
    assert len(py_files) >= 2, f"Expected at least bar_state.py and bar_position.py in {tb_dir}"

    all_violations: list[str] = []
    for py_file in py_files:
        violations = scan_file_for_violations(py_file)
        all_violations.extend(violations)

    assert not all_violations, "Found violations in traffic_bar:\n" + "\n".join(all_violations)


def test_scanner_self_validation(tmp_path):
    """自我驗證：驗證掃描器能有效攔截違規 import 與 focus_force。"""
    # 測試違規 import
    bad_import_file = tmp_path / "bad_import.py"
    bad_import_file.write_text("import wave\nimport pyaudio\n", encoding="utf-8")
    v1 = scan_file_for_violations(bad_import_file)
    assert any("Forbidden import 'wave'" in item for item in v1)
    assert any("Forbidden import 'pyaudio'" in item for item in v1)

    # 測試違規 import from
    bad_from_file = tmp_path / "bad_from.py"
    bad_from_file.write_text("from sounddevice import InputStream\n", encoding="utf-8")
    v2 = scan_file_for_violations(bad_from_file)
    assert any("Forbidden import from 'sounddevice'" in item for item in v2)

    # 測試違規 focus_force
    bad_focus_file = tmp_path / "bad_focus.py"
    bad_focus_file.write_text("root.focus_force()\n", encoding="utf-8")
    v3 = scan_file_for_violations(bad_focus_file)
    assert any("Forbidden call 'focus_force'" in item for item in v3)

    # 註解中的 focus_force 應被忽略
    comment_file = tmp_path / "comment_focus.py"
    comment_file.write_text("# Do not use focus_force here\nx = 1 # note: focus_force\n", encoding="utf-8")
    v4 = scan_file_for_violations(comment_file)
    assert len(v4) == 0
