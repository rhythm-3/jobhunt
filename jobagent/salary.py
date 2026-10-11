"""Salary extraction from listing text. INR as lakhs-per-annum (LPA); USD as annual dollars. No FX conversion."""
from __future__ import annotations

import re

_INR_L = re.compile(r"₹\s*([\d.]+)\s*L(?:akh)?s?\b(?:\s*[-–to]+\s*₹?\s*([\d.]+)\s*L(?:akh)?s?\b)?", re.I)
_INR_WORDS = re.compile(r"([\d.]+)\s*(?:lacs?|lakhs?|lpa)?\s*(?:-|–|to)\s*([\d.]+)\s*(?:lacs?|lakhs?|lpa)\b", re.I)
_USD = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*(k)?\s*(?:-|–|to)\s*\$?\s?([\d,]+(?:\.\d+)?)\s*(k)?", re.I)


def parse_salary(text: str) -> dict | None:
    t = text or ""
    m = _INR_L.search(t)
    if m:
        lo = float(m.group(1)); hi = float(m.group(2) or lo)
        return _mk("INR", lo, hi, f"₹{_f(lo)}–{_f(hi)} LPA" if hi != lo else f"₹{_f(lo)} LPA")
    m = _INR_WORDS.search(t)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return _mk("INR", lo, hi, f"₹{_f(lo)}–{_f(hi)} LPA")
    m = _USD.search(t)
    if m:
        lo = float(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1)
        hi = float(m.group(3).replace(",", "")) * (1000 if m.group(4) else 1)
        if 10_000 <= lo <= hi <= 2_000_000:
            return _mk("USD", lo, hi, f"${lo / 1000:.0f}k–{hi / 1000:.0f}k")
    return None


def _f(x: float) -> str:
    return f"{x:g}"


def _mk(cur, lo, hi, label):
    if lo > hi:
        lo, hi = hi, lo
    if cur == "INR" and not (0.5 <= lo <= 500):
        return None
    return {"currency": cur, "min": lo, "max": hi, "label": label}
