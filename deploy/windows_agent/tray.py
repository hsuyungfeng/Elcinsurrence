"""Windows Agent system tray implementation using pystray (Phase 32 Plan 32-05, B5).

Pure logic specifications and cross-thread queue dispatch to ensure
Tkinter main thread safety.
"""

from __future__ import annotations

import logging
import queue
import sys
from pathlib import Path
from typing import Any, List, Optional, Tuple

logger = logging.getLogger("windows_agent.tray")

TRAY_ACTIONS = frozenset({"toggle_bar", "connection_status", "recalibrate", "quit"})


def build_menu_spec(bar_visible: bool, connection_text: str) -> List[Tuple[str, str]]:
    """Build the 4-item menu specification: (label, action_key)."""
    toggle_label = "隱藏快捷列" if bar_visible else "顯示快捷列"
    conn_label = f"連線狀態：{connection_text}"
    return [
        (toggle_label, "toggle_bar"),
        (conn_label, "connection_status"),
        ("重新校正 HIS", "recalibrate"),
        ("結束", "quit"),
    ]


class TrayController:
    """Dispatches tray menu clicks into a thread-safe Queue for Tkinter main loop."""

    def __init__(self, action_queue: queue.Queue[str]):
        self.action_queue = action_queue

    def dispatch(self, action_key: str) -> None:
        if action_key in TRAY_ACTIONS:
            self.action_queue.put(action_key)
        else:
            logger.warning("Ignored unknown tray action key: %s", action_key)


def _create_default_icon_image():
    """Create a 16x16 green circle fallback icon if PIL is available."""
    try:
        from PIL import Image, ImageDraw

        image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((1, 1, 14, 14), fill="#43A047", outline="#2E7D32")
        return image
    except Exception as exc:
        logger.warning("Could not create fallback icon image: %s", exc)
        return None


def start_tray(
    controller: TrayController,
    icon_image_path: Optional[str] = None,
    bar_visible: bool = True,
    connection_text: str = "就緒",
) -> Optional[Any]:
    """Start pystray in detached background thread.

    Returns icon object or None if unsupported or failed.
    """
    if sys.platform != "win32":
        return None

    try:
        import pystray
        from PIL import Image

        if icon_image_path and Path(icon_image_path).is_file():
            img = Image.open(icon_image_path)
        else:
            img = _create_default_icon_image()

        if img is None:
            logger.warning("Cannot start tray: no icon image available")
            return None

        menu_items = []
        for label, key in build_menu_spec(bar_visible, connection_text):
            # Capture action_key in closure
            def make_handler(k: str):
                return lambda icon, item: controller.dispatch(k)

            menu_items.append(pystray.MenuItem(label, make_handler(key)))

        icon = pystray.Icon(
            name="ElcAgent",
            icon=img,
            title="Elcinsurrence Agent",
            menu=pystray.Menu(*menu_items),
        )
        icon.run_detached()
        return icon
    except ImportError:
        logger.warning("pystray or PIL not installed; system tray disabled.")
        return None
    except Exception as exc:
        logger.warning("Failed to start system tray icon: %s", exc)
        return None
