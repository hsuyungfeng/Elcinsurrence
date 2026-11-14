"""Test utility to read combined workbench source (Phase 32 Plan 32-16, E8).

Returns concatenated static/index.html, static/css/workbench.css, and static/js/workbench.js
so existing tests asserting strings in workbench source continue to pass after file split.
"""

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def read_workbench_source() -> str:
    """Read and return combined content of workbench HTML, CSS, and JS."""
    static_dir = _PROJECT_ROOT / "static"
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    css_file = static_dir / "css" / "workbench.css"
    css = css_file.read_text(encoding="utf-8") if css_file.exists() else ""
    js_file = static_dir / "js" / "workbench.js"
    js = js_file.read_text(encoding="utf-8") if js_file.exists() else ""

    return f"{html}\n<style>\n{css}\n</style>\n<script>\n{js}\n</script>\n"
