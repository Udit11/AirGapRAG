"""
Local Whisper STT
Uses faster-whisper (CPU-optimised) for offline speech-to-text.
Handles Indian English, Hindi, and Gujarati accents reliably.

Install once:
    pip install faster-whisper --break-system-packages

Model is downloaded once and cached locally at ~/.cache/huggingface/
For fully air-gapped use, download the model files separately and
set WHISPER_MODEL_PATH to the local folder.
"""

import os
import io
import logging
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

# ── Model config ────────────────────────────────────────────────────────────
# "base"   → fastest, ~74MB,  good for clear speech
# "small"  → balanced, ~244MB, recommended for accented English  ← USE THIS
# "medium" → best accuracy, ~769MB, use if small misses words
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small")

# For air-gapped: set this env var to the folder containing model files
# e.g. WHISPER_MODEL_PATH = "/opt/whisper_models/small"
WHISPER_MODEL_PATH = os.getenv("WHISPER_MODEL_PATH", None)

_whisper_model = None


def _load_model():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError(
            "faster-whisper is not installed.\n"
            "Run: pip install faster-whisper --break-system-packages"
        )

    model_path = WHISPER_MODEL_PATH or WHISPER_MODEL_SIZE

    log.info("Loading Whisper model: %s (this takes ~10s on first load)...", model_path)

    _whisper_model = WhisperModel(
        model_path,
        device="cpu",
        compute_type="int8",   # int8 is fastest on CPU, no quality loss for STT
    )

    log.info("Whisper model loaded.")
    return _whisper_model


import re as _re

_CORRECTION_MARKERS = [
    r"\bsorry\b", r"\bno wait\b", r"\bactually\b", r"\bi mean\b",
    r"\bcorrection\b", r"\blet me rephrase\b", r"\blet me repeat\b",
    r"\bnot that\b", r"\bignore that\b", r"\bscratch that\b",
    r"\bmaaf\b", r"\bmaafi\b", r"\bnahin\b", r"\bnahi\b",
]

_LEADING_FILLERS = _re.compile(
    r"^(um+|uh+|hmm+|ah+|err+|okay so|so|well|right|now|"
    r"shakti|hey shakti|hello shakti|"
    r"haan|acha|theek hai|ha|saro)[,\s]+",
    flags=_re.IGNORECASE,
)


def extract_intended_question(transcript: str) -> str:
    """
    Clean a raw Whisper transcript of false starts and filler words.

    1. If a correction marker is found ("sorry", "I mean", etc.),
       take only the text AFTER the last correction marker.
    2. Strip leading filler words.
    3. Capitalise first letter.

    Examples:
      "Shakti watch the use of, sorry, how to dismantle a valve"
        → "How to dismantle a valve"
      "um uh how to isolate the compressor"
        → "How to isolate the compressor"
    """
    if not transcript:
        return transcript

    text = transcript.strip()

    # Find the LAST correction marker and take everything after it
    last_cut = -1
    for pattern in _CORRECTION_MARKERS:
        for m in _re.finditer(pattern, text, flags=_re.IGNORECASE):
            if m.end() > last_cut:
                last_cut = m.end()

    if last_cut > 0:
        text = text[last_cut:].strip().lstrip(",.;:- ")
        # After a correction marker, if the text doesn't start with an
        # interrogative / action word, scan forward to find where the
        # real question begins (e.g. "not watch the use of, HOW TO...")
        QUESTION_STARTERS = _re.compile(
            r"\b(how|what|when|where|which|who|why|steps|procedure|"
            r"dismantle|remove|install|isolate|replace|start|shutdown|"
            r"explain|describe|tell me)\b",
            flags=_re.IGNORECASE,
        )
        m = QUESTION_STARTERS.search(text)
        if m and m.start() > 0:
            text = text[m.start():].strip()

    # Strip leading filler words repeatedly until none remain
    prev = None
    while prev != text:
        prev = text
        text = _LEADING_FILLERS.sub("", text).strip()

    if text:
        text = text[0].upper() + text[1:]

    return text or transcript


def transcribe_audio(audio_bytes: bytes, language: str = "en") -> dict:
    """
    Transcribe audio bytes (WebM/WAV/MP3) to text using local Whisper.

    Parameters
    ----------
    audio_bytes : raw audio file bytes from the browser MediaRecorder
    language    : ISO language code — "en", "hi", "gu"
                  Pass None to let Whisper auto-detect (slightly slower)

    Returns
    -------
    {"transcript": str, "language": str, "confidence": float}
    """
    model = _load_model()

    # Write bytes to a temp file — faster-whisper needs a file path.
    # Use .webm suffix but also try converting to wav on decode error.
    # Chrome on Windows produces webm/opus which PyAV sometimes rejects.
    # No suffix — let ffmpeg/PyAV auto-detect the container format.
    # Chrome on Windows can produce webm, ogg, or mp4 depending on codec support.
    with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    # If PyAV can't read the webm, convert it to wav using ffmpeg subprocess
    def _ensure_wav(path: str) -> str:
        """Try to convert to wav if the file can't be opened by PyAV."""
        import subprocess, shutil
        if not shutil.which("ffmpeg"):
            return path  # ffmpeg not available, try as-is
        wav_path = path + ".wav"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", path,
                 "-ar", "16000", "-ac", "1", "-f", "wav", wav_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=True,
            )
            return wav_path
        except Exception:
            return path  # conversion failed, try original

    try:
        segments, info = model.transcribe(
            tmp_path,
            language=language,
            beam_size=3,
            vad_filter=True,
            vad_parameters={
                "min_silence_duration_ms": 500,
            },
            # initial_prompt does two jobs:
            # 1. Seeds domain vocabulary for better recognition of
            #    technical terms.
            # 2. Demonstrates clean question style — biases Whisper
            #    away from transcribing filler words and false starts.
            initial_prompt=(
                "Industrial maintenance assistant."
                "Operator asks direct technical questions. "
                "Technical terms: compressor, valve, isolate, overhaul, "
                "dismantle, bearing, coupling, pressure, shutdown, "
                "delivery valve, suction valve, piston, cylinder, "
                "lubrication, torque, gasket, flange, impeller. "
                "Questions are clear and complete. "
                "How to dismantle the delivery valve? "
                "What are the steps to isolate the compressor? "
                "How to replace the bearing assembly?"
            ),
            suppress_tokens=[-1],
        )

        raw_transcript = " ".join(seg.text.strip() for seg in segments).strip()
        transcript     = extract_intended_question(raw_transcript)

        log.info("Whisper raw:     '%s'", raw_transcript)
        log.info("Whisper cleaned: '%s' (lang=%s, prob=%.2f)",
                 transcript, info.language, info.language_probability)

        return {
            "transcript":     transcript,
            "raw_transcript": raw_transcript,
            "language":       info.language,
            "confidence":     round(info.language_probability, 3),
        }

    except Exception as e:
        # If webm decode failed, try converting to wav first
        if "InvalidDataError" in type(e).__name__ or "Invalid data" in str(e):
            log.warning("WebM decode failed, attempting WAV conversion...")
            wav_path = _ensure_wav(tmp_path)
            if wav_path != tmp_path:
                try:
                    segments, info = model.transcribe(
                        wav_path,
                        language=language,
                        beam_size=3,
                        vad_filter=True,
                        vad_parameters={"min_silence_duration_ms": 500},
                        initial_prompt=(
                            "Industrial maintenance assistant. "
                            "Operator asks direct technical questions. "
                            "Technical terms: compressor, valve, isolate, overhaul, "
                            "dismantle, bearing, coupling, pressure, shutdown, "
                            "delivery valve, suction valve, piston, cylinder, "
                            "lubrication, torque, gasket, flange, impeller."
                        ),
                        suppress_tokens=[-1],
                    )
                    raw_transcript = " ".join(seg.text.strip() for seg in segments).strip()
                    transcript = extract_intended_question(raw_transcript)
                    log.info("WAV fallback transcript: '%s'", transcript)
                    return {
                        "transcript":     transcript,
                        "raw_transcript": raw_transcript,
                        "language":       info.language,
                        "confidence":     round(info.language_probability, 3),
                    }
                except Exception as e2:
                    log.error("WAV fallback also failed: %s", e2)
                finally:
                    Path(wav_path).unlink(missing_ok=True)
        raise
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        # Clean up any wav conversion artifact
        wav_artifact = Path(tmp_path + ".wav")
        if wav_artifact.exists():
            wav_artifact.unlink(missing_ok=True)