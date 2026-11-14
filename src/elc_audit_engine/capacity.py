"""Capacity sampling, runway forecasting and growth rate calculation (Phase 32 Plan 32-08, D3, D5, D6).

All algorithms are pure standard library. This module contains zero deletion logic
to strictly comply with clinic data retention policy (D-32-04).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("elc_audit_engine.capacity")

#: 預估剩餘天數門檻（D-32-13 裁示：黃燈 180 天、紅燈 90 天）
DEFAULT_YELLOW_DAYS = int(os.getenv("ELC_CAPACITY_YELLOW_DAYS", "180"))
DEFAULT_RED_DAYS = int(os.getenv("ELC_CAPACITY_RED_DAYS", "90"))

MAX_SAMPLES_HISTORY = 400


def directory_size_bytes(dir_path: str | Path) -> int:
    """Recursively calculate total bytes in directory without following symlinks."""
    total = 0
    p = Path(dir_path)
    if not p.is_dir():
        return 0

    try:
        with os.scandir(p) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += directory_size_bytes(entry.path)
                except OSError:
                    continue
    except OSError:
        pass

    return total


def growth_bytes_per_day(samples: List[Tuple[str, int]]) -> Optional[float]:
    """Calculate daily growth slope using least-squares linear regression.

    Requires at least 7 daily samples to avoid wild extrapolations.
    Returns None if insufficient samples or if slope <= 0 (flat / shrinking).
    """
    if len(samples) < 7:
        return None

    # Sort by date string
    sorted_samples = sorted(samples, key=lambda s: s[0])

    n = len(sorted_samples)
    # Convert dates to relative day index 0..n-1
    xs = list(range(n))
    ys = [float(s[1]) for s in sorted_samples]

    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xx = sum(x * x for x in xs)
    sum_xy = sum(x * y for x, y in zip(xs, ys))

    denom = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return None

    slope = (n * sum_xy - sum_x * sum_y) / denom
    if slope <= 0:
        return None

    return float(slope)


def days_until_full(samples: List[Tuple[str, int]], free_bytes: int) -> Optional[float]:
    """Calculate estimated days until disk is full based on daily growth rate."""
    if len(samples) < 7:
        return None

    growth = growth_bytes_per_day(samples)
    if growth is None or growth <= 0:
        return None

    return float(free_bytes) / growth


def classify_runway(
    days: Optional[float],
    yellow_days: int = DEFAULT_YELLOW_DAYS,
    red_days: int = DEFAULT_RED_DAYS,
) -> str:
    """Classify runway days into green, yellow, red, or unknown (D-32-13)."""
    if days is None:
        return "unknown"
    if days <= red_days:
        return "red"
    if days <= yellow_days:
        return "yellow"
    return "green"


def record_daily_sample(
    data_dir: str | Path,
    store_path: str | Path,
    today: Optional[str] = None,
) -> Dict[str, Any]:
    """Record today's data directory size into store_path JSON file idempotently.

    Note: Capping history at 400 entries limits the sample history size only,
    and never modifies or deletes any actual patient record data.
    """
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")

    current_size = directory_size_bytes(data_dir)

    target_file = Path(store_path)
    samples: List[Dict[str, Any]] = []

    if target_file.is_file():
        try:
            content = target_file.read_text(encoding="utf-8")
            loaded = json.loads(content)
            if isinstance(loaded, list):
                samples = [s for s in loaded if isinstance(s, dict) and "date" in s and "bytes" in s]
        except Exception as exc:
            logger.warning("Failed to read existing capacity samples from %s: %s", store_path, exc)

    # Update today's entry if exists, else append
    updated = False
    for item in samples:
        if item.get("date") == today:
            item["bytes"] = current_size
            updated = True
            break

    if not updated:
        samples.append({"date": today, "bytes": current_size})

    # Sort by date
    samples.sort(key=lambda s: str(s.get("date", "")))

    # Cap at MAX_SAMPLES_HISTORY (keeps recent records)
    if len(samples) > MAX_SAMPLES_HISTORY:
        samples = samples[-MAX_SAMPLES_HISTORY:]

    # Atomic write using temp file and os.replace (no delete or remove)
    target_file.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target_file.with_name(f".{target_file.name}.tmp")
    temp_target.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_target, target_file)

    return {"date": today, "bytes": current_size}
