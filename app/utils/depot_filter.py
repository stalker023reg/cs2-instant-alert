"""
CS2 Instant Alert — Depot Filtering & Utilities.

Filters out noise (macOS depots, server depots, raw technical IDs)
so that users only see relevant client game components.
"""

from __future__ import annotations

from typing import Any

# ─── Client CS2 Depot IDs → Human-readable names ───
CS2_DEPOT_NAMES: dict[int, str] = {
    730: "CS2 Shared Content",
    731: "CS2 Client Content",
    733: "CS2 Binaries (Win64)",
    734: "CS2 Binaries (Linux64)",
    2347770: "CS2 Content (Win64)",
    2347771: "CS2 Content (Linux64)",
}

# Server depots to exclude (server updates not needed)
SERVER_DEPOT_IDS: set[int] = {732, 2347773}

# Depots to strictly exclude (macOS is unsupported, empty/legacy depots)
MACOS_DEPOT_IDS: set[int] = {735, 2347779}


def filter_depots(depot_changes: dict[str, Any] | list[Any] | None) -> tuple[list[dict[str, Any]], int]:
    """
    Filter depot changes:
    1. Discard macOS depots.
    2. Discard Dedicated Server depots.
    3. Keep only recognized client components.
    4. Collapse unrecognized technical depots into a count.

    Returns:
        (filtered_depots, technical_depots_count)
    """
    if not depot_changes:
        return [], 0

    filtered: list[dict[str, Any]] = []
    technical_count = 0

    # Normalise input into an iterable of (depot_id, depot_data)
    items: list[tuple[str, Any]] = []
    if isinstance(depot_changes, dict):
        items = list(depot_changes.items())
    elif isinstance(depot_changes, list):
        items = [(str(d), {}) if not isinstance(d, dict) else (str(d.get("depot_id", "")), d) for d in depot_changes]

    seen_ids: set[int] = set()

    for key, val in items:
        try:
            depot_id = int(key)
        except (ValueError, TypeError):
            continue

        if depot_id in seen_ids:
            continue
        seen_ids.add(depot_id)

        # 1. Exclude macOS depots
        if depot_id in MACOS_DEPOT_IDS:
            continue

        depot_name = ""
        if isinstance(val, dict):
            depot_name = val.get("name") or ""

        if "macos" in depot_name.lower() or "osx" in depot_name.lower():
            continue

        # 2. Exclude Dedicated Server depots
        if depot_id in SERVER_DEPOT_IDS or "server" in depot_name.lower():
            continue

        # 3. Match recognized CS2 client depots
        if depot_id in CS2_DEPOT_NAMES:
            name = CS2_DEPOT_NAMES[depot_id]
            filtered.append({
                "depot_id": depot_id,
                "name": name,
                "data": val if isinstance(val, dict) else {},
            })
        else:
            # 4. Technical numeric depots without mapping
            technical_count += 1

    return filtered, technical_count


def determine_criticality(depot_changes: dict[str, Any] | list[Any] | None) -> tuple[bool, str]:
    """Return standard update status."""
    return False, "Обновление"


def format_depots_html(filtered_depots: list[dict[str, Any]], technical_count: int = 0) -> str:
    """Format filtered depots into clean Telegram HTML."""
    lines: list[str] = []
    for d in filtered_depots:
        lines.append(f"  📦 <b>{d['name']}</b>")

    if technical_count > 0:
        lines.append(f"  📦 <i>Прочие технические депоты ({technical_count} шт.)</i>")

    return "\n".join(lines)
