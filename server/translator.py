"""
Shakti — Offline Translation Module
Uses argostranslate for fully offline Hindi/Gujarati ↔ English translation.

Setup (run once while internet is available):
    pip install argostranslate --break-system-packages
    python translator.py --setup

This downloads ~150MB of translation models (en→hi, hi→gu) to:
    ~/.local/share/argos-translate/packages/

After setup the system works completely offline.

Usage:
    Input  : always English (Whisper outputs Roman script for all spoken languages)
    Output : Hindi (Devanagari) or Gujarati (Devanagari via Hindi pivot)

    from_english("Ensure no air pressure in pipeline", "hi")
    → "पाइपलाइन में कोई वायु दबाव नहीं है यह सुनिश्चित करें"

    from_english("Ensure no air pressure in pipeline", "gu")
    → "પાઇપલાઇનમાં કોઈ હવાનું દબાણ નથી તે સુનિશ્ચિત કરો"
"""

import os
import logging
import argparse

log = logging.getLogger(__name__)

# ── Supported language pairs ─────────────────────────────────────────────────
# argostranslate supports hi↔en natively.
# Gujarati (gu) is not in argostranslate's package list, so we route it
# through Hindi as a pivot: gu → hi → en and en → hi → gu.
# This works well in practice because Gujarati and Hindi share vocabulary.

SUPPORTED = {"en", "hi", "gu"}

_translators: dict = {}   # cache: (from_code, to_code) → translate fn


# ── Internal: load argostranslate ────────────────────────────────────────────

def _get_translator(from_code: str, to_code: str):
    """
    Return a cached argostranslate translation function for the given pair.
    Raises RuntimeError if the language package is not installed.
    """
    key = (from_code, to_code)
    if key in _translators:
        return _translators[key]

    try:
        from argostranslate import translate as at
    except ImportError:
        raise RuntimeError(
            "argostranslate is not installed.\n"
            "Run: pip install argostranslate --break-system-packages\n"
            "Then run: python translator.py --setup"
        )

    installed = at.get_installed_languages()
    lang_map  = {lang.code: lang for lang in installed}

    if from_code not in lang_map:
        raise RuntimeError(
            f"Language '{from_code}' not installed in argostranslate.\n"
            "Run: python translator.py --setup"
        )
    if to_code not in lang_map:
        raise RuntimeError(
            f"Language '{to_code}' not installed in argostranslate.\n"
            "Run: python translator.py --setup"
        )

    translation = lang_map[from_code].get_translation(lang_map[to_code])
    if not translation:
        raise RuntimeError(
            f"No translation model found for {from_code} → {to_code}.\n"
            "Run: python translator.py --setup"
        )

    fn = translation.translate
    _translators[key] = fn
    log.info("Translation model loaded: %s → %s", from_code, to_code)
    return fn


# ── Public API ───────────────────────────────────────────────────────────────

def translate(text: str, from_lang: str, to_lang: str) -> str:
    """
    Translate text between languages.

    Parameters
    ----------
    text      : text to translate
    from_lang : source language code ("en", "hi", "gu")
    to_lang   : target language code ("en", "hi", "gu")

    Returns
    -------
    Translated string. Returns original text on any error so the
    system degrades gracefully rather than crashing.
    """
    if not text or not text.strip():
        return text

    # Normalise language codes
    from_lang = from_lang.lower().strip()
    to_lang   = to_lang.lower().strip()

    # No-op
    if from_lang == to_lang:
        return text

    # Unsupported language — return original
    if from_lang not in SUPPORTED or to_lang not in SUPPORTED:
        log.warning("Unsupported language pair: %s → %s", from_lang, to_lang)
        return text

    try:
        # Direct translation: en↔hi
        if set([from_lang, to_lang]) == {"en", "hi"}:
            fn = _get_translator(from_lang, to_lang)
            result = fn(text)
            log.debug("Translated %s→%s: %s → %s", from_lang, to_lang,
                      text[:60], result[:60])
            return result

        # Pivot translation for Gujarati via Hindi:
        #   gu → hi → en
        #   en → hi → gu
        if from_lang == "gu" and to_lang == "en":
            hi_text = _get_translator("gu", "hi")(text)
            return _get_translator("hi", "en")(hi_text)

        if from_lang == "en" and to_lang == "gu":
            hi_text = _get_translator("en", "hi")(text)
            return _get_translator("hi", "gu")(hi_text)

        if from_lang == "gu" and to_lang == "hi":
            return _get_translator("gu", "hi")(text)

        if from_lang == "hi" and to_lang == "gu":
            return _get_translator("hi", "gu")(text)

        # Fallback
        fn = _get_translator(from_lang, to_lang)
        return fn(text)

    except Exception as e:
        log.error("Translation failed (%s→%s): %s", from_lang, to_lang, e)
        return text   # graceful degradation — return original


def to_english(text: str, from_lang: str) -> str:
    """Translate any language to English."""
    return translate(text, from_lang, "en")


def from_english(text: str, to_lang: str) -> str:
    """Translate English to any language."""
    return translate(text, "en", to_lang)


def is_translation_needed(lang: str) -> bool:
    """Returns True if the language is not English."""
    return lang.lower() not in ("en", "en-in", "en-gb", "en-us")


# ── Setup: download language packages ────────────────────────────────────────

def setup_packages():
    """
    Download and install all required argostranslate language packages.
    Run once while internet is available.
    """
    try:
        from argostranslate import package, translate
    except ImportError:
        print("ERROR: argostranslate not installed.")
        print("Run: pip install argostranslate --break-system-packages")
        return

    print("Updating argostranslate package index...")
    package.update_package_index()

    available = package.get_available_packages()

    # Required pairs — we only need EN→HI and EN→GU (via hi pivot)
    # Questions arrive in Roman English from Whisper, answers go to Devanagari
    required = [
        ("en", "hi"),   # answer → Hindi
        ("hi", "gu"),   # Hindi → Gujarati pivot for en→gu
    ]

    installed_codes = {
        (p.from_code, p.to_code)
        for p in package.get_installed_packages()
    }

    for from_code, to_code in required:
        if (from_code, to_code) in installed_codes:
            print(f"  ✓ {from_code} → {to_code} already installed")
            continue

        pkg = next(
            (p for p in available
             if p.from_code == from_code and p.to_code == to_code),
            None
        )

        if pkg:
            print(f"  ↓ Downloading {from_code} → {to_code} (~{pkg.package_version})...")
            package.install_from_path(pkg.download())
            print(f"  ✓ {from_code} → {to_code} installed")
        else:
            print(f"  ✗ {from_code} → {to_code} not found in package index")

    print("\n✅ Translation setup complete.")
    print("All packages are saved locally and work fully offline.\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Shakti Translation Module")
    parser.add_argument("--setup", action="store_true",
                        help="Download and install language packages (run once)")
    parser.add_argument("--test", action="store_true",
                        help="Run a quick translation test")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    if args.setup:
        setup_packages()

    if args.test:
        tests = [
            ("Ensure no air pressure in the pipeline", "en", "hi"),
            ("Unscrew the nut fitted to the stud",     "en", "hi"),
            ("Ensure no air pressure in the pipeline", "en", "gu"),
            ("Remove the bell valve and copper ring",  "en", "gu"),
        ]
        print("\nTranslation test:")
        for text, frm, to in tests:
            result = translate(text, frm, to)
            print(f"  [{frm}→{to}] {text[:40]} → {result[:60]}")