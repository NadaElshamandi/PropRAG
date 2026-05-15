"""
neighborhoods.py
----------------
Canonical Alexandria district normalizer.
Maps English, Arabic, and common misspellings to a single canonical name.

Usage:
    from scrapers.neighborhoods import normalize_district
    normalize_district("Glym")       # → "Glym"
    normalize_district("جليم")       # → "Glym"
    normalize_district("sidi gabber") # → "Sidi Gaber"
"""

from typing import Optional

# ── Canonical mapping: canonical_name → [aliases] ─────────────────────────────

_ALEXANDRIA_DISTRICTS: dict[str, list[str]] = {
    "Smouha": ["smouha", "smoha", "smou7a", "سمouha", "سموحة", "السموحة"],
    "Sidi Gaber": [
        "sidi gaber", "sidi gabber", "sidigaber", "sidi-gaber",
        "سيدي جابر", "سيدى جابر", "sidigabr",
    ],
    "Glym": [
        "glym", "glim", "gleem", "gleyem", "glyem",
        "جليم", "جلىم", "جليم", "الجليم",
    ],
    "Kafr Abdou": [
        "kafr abdou", "kafrelabdou", "kafr abdo", "kafrelabdo",
        "كفر عبده", "كفر عبدة", "كفر عبدو",
    ],
    "San Stefano": [
        "san stefano", "san stefanu", "santa stefano",
        "سان ستيفانو", "سان استيفانو", "سانت ستيفانو",
    ],
    "Loran": ["loran", "lorane", "لوران", "اللوران", "lorane"],
    "Saray": ["saray", "saraya", "saraya", "سراي", "السراي", "سرايا"],
    "Miami": ["miami", "mayami", "ميامي", "الميامي", "مايامي"],
    "Agami": ["agami", "el agami", "العجمي", "عجمي", "agamy"],
    "Montaza": [
        "montaza", "mantaza", "montazah", "almontaza",
        "المنتزة", "منتزة", "منتزه", "المنتزه",
    ],
    "Ibrahimeya": [
        "ibrahimeya", "ibrahimeyya", "ibrahimiya", "el ibrahimeya",
        "الإبراهيمية", "إبراهيمية", "ابراهيمية",
    ],
    "Sporting": [
        "sporting", "sportng", "sporting el raml",
        "سبورتنج", "سبورتينج", "السبورتنج",
    ],
    "Cleopatra": [
        "cleopatra", "cleopetra", "cleoptra",
        "كليوباترا", "كليوبترا", "كليوباتra",
    ],
    "Fleming": ["fleming", "flemeng", "فلمنج", "الفلمنج", "فليمنج"],
    "Stanley": ["stanley", "stanly", "stanely", "ستانلي", "ستانلي"],
    "Roushdy": ["roushdy", "roshdy", "roushdi", "roshdi", "رشدي", "الرشدي"],
    "Camp Caesar": [
        "camp caesar", "camp caeser", "campkaesar", "kamp caesar",
        "كامب شيزار", "كامب قيصر", "كمب شيزار",
    ],
    "Bolkly": ["bolkly", "bolkley", "bolkli", "بولكلي", "بولكلى", "ال بولكلي"],
    "Zizenia": ["zizenia", "zizinia", "zizinia", "زيزينيا", "زيزينيا", "زيزينيا"],
    "Asafra": ["asafra", "al asafra", "el asafra", "العصافرة", "عصافرة"],
    "Mandara": ["mandara", "almandara", "el mandara", "المندرة", "مندرة"],
    "Saba Pasha": [
        "saba pasha", "sabaa pasha", "saba pacha",
        "سبا باشا", "سبع باشا", "سبا باشا",
    ],
    "Hadara": ["hadara", "el hadara", "hadara", "الحضرة", "حضرة"],
    "Moharam Bek": [
        "moharam bek", "moharam beik", "moharambeck", "moharam beek",
        "محرم بك", "محرم بيك", "المحرم بك",
    ],
    "Gomrok": ["gomrok", "gomrok", "gomruk", "الجمرك", "جمرك", "gomrouk"],
    "Kom El Deka": [
        "kom el deka", "kom eldeka", "kom el deka", "komel deka",
        "كوم الدكة", "كوم الدكه", "الكوم",
    ],
    "Bab Sharq": [
        "bab sharq", "bab elsharq", "bab sharak",
        "باب شرق", "باب الشرق", "باب شرقي",
    ],
    "Attarin": [
        "attarin", "attarin", "atarin", "el attarin",
        "العطارين", "عطارين", "عتارين",
    ],
    "Mansheya": [
        "mansheya", "manshia", "mansheya", "el mansheya",
        "المنشية", "منشية", "منشيه",
    ],
    "Wardian": ["wardian", "wardiane", "wardian", "الورديان", "ورديان"],
    "Amreya": ["amreya", "amreia", "amria", "العامرية", "عامرية", "عامريه"],
    "Borg El Arab": [
        "borg el arab", "burj el arab", "borg elarab", "burg el arab",
        "برج العرب", "بورج العرب", "برج عرب",
    ],
    # Broader catch-all areas (not strictly districts but common in listings)
    "Alexandria": [
        "alexandria", "alex", "iskandaria", "eskandaria",
        "الاسكندرية", "إسكندرية", "اسكندرية", "الإسكندرية",
    ],
}

# Flatten into a lookup table: alias_lower → canonical
_ALIAS_MAP: dict[str, str] = {}
for canonical, aliases in _ALEXANDRIA_DISTRICTS.items():
    # Always map the canonical name itself
    _ALIAS_MAP[canonical.lower()] = canonical
    for alias in aliases:
        _ALIAS_MAP[alias.lower()] = canonical


def normalize_district(raw: Optional[str]) -> Optional[str]:
    """
    Normalize a raw district/neighborhood string to its canonical form.

    - Strips extra whitespace
    - Case-insensitive match
    - Falls back to returning the cleaned raw string if no match found
      (so we don't lose data, just flag it for review later)

    Returns None if raw is empty/None.
    """
    if not raw:
        return None

    cleaned = raw.strip()
    key = cleaned.lower()

    # Direct alias match
    if key in _ALIAS_MAP:
        return _ALIAS_MAP[key]

    # Substring match (e.g. "Apartment in Smouha" → "Smouha")
    for alias, canonical in _ALIAS_MAP.items():
        if alias in key or key in alias:
            return canonical

    # No match — return cleaned raw string as-is
    return cleaned


def list_canonical_districts() -> list[str]:
    """Return all known canonical district names."""
    return list(_ALEXANDRIA_DISTRICTS.keys())


def is_valid_district(raw: Optional[str]) -> bool:
    """Check if a raw string maps to a known canonical district."""
    return normalize_district(raw) in _ALEXANDRIA_DISTRICTS
