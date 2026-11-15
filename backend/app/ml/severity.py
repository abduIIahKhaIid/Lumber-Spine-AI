"""Severity vocabulary and colors shared by rendering, reports and the API."""

from __future__ import annotations

NORMAL, MODERATE, SEVERE = "Normal/Mild", "Moderate", "Severe"
ORDER = (NORMAL, MODERATE, SEVERE)
RANK = {NORMAL: 0, MODERATE: 1, SEVERE: 2}

# RGB colors: green / yellow / red. Mirrored in frontend/lib/severity.ts.
COLORS = {NORMAL: (34, 197, 94), MODERATE: (234, 179, 8), SEVERE: (239, 68, 68)}
HEX = {name: "#{:02x}{:02x}{:02x}".format(*rgb) for name, rgb in COLORS.items()}

_ALIASES = {
    "normal_mild": NORMAL,
    "normal/mild": NORMAL,
    "normal": NORMAL,
    "mild": NORMAL,
    "moderate": MODERATE,
    "severe": SEVERE,
}


def canonical(name: str) -> str:
    return _ALIASES.get(str(name).strip().lower(), str(name))


def ordered_scores(scores: dict[str, float]) -> dict[str, float]:
    """Return scores keyed and ordered Normal/Mild, Moderate, Severe."""
    mapped = {canonical(key): float(value) for key, value in scores.items()}
    return {name: round(mapped.get(name, 0.0), 4) for name in ORDER}


def color(severity: str) -> tuple[int, int, int]:
    return COLORS.get(canonical(severity), (148, 163, 184))
