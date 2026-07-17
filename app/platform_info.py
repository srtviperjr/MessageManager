"""Detect Mac architecture (Apple Silicon vs Intel) and related capabilities."""

from __future__ import annotations

import platform
import subprocess
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def is_apple_silicon() -> bool:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return True
    # Rosetta processes report x86_64; probe for underlying Apple Silicon.
    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.optional.arm64"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        return result.stdout.strip() == "1"
    except (OSError, subprocess.SubprocessError):
        return False


@lru_cache(maxsize=1)
def chip_name() -> str:
    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        brand = (result.stdout or "").strip()
        if brand:
            return brand
    except (OSError, subprocess.SubprocessError):
        pass
    return platform.processor() or platform.machine() or "Unknown CPU"


@lru_cache(maxsize=1)
def architecture() -> str:
    return platform.machine() or "unknown"


def platform_status() -> dict[str, Any]:
    silicon = is_apple_silicon()
    return {
        "apple_silicon": silicon,
        "architecture": architecture(),
        "chip": chip_name(),
        "label": "Apple Silicon" if silicon else "Intel",
        "summary_backend": "apple_intelligence" if silicon else "extractive",
    }
