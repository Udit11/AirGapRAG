import logging
import time
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from rag_pipeline import ask_rag, is_procedure_query, get_cache
from session_manager import (
    create_session, get_current_step, next_step, get_session_summary
)
from whisper_stt import transcribe_audio
from translator import from_english, is_translation_needed

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(
    title="AI Assistant",
    description="Safety-critical RAG assistant with local Whisper STT and translation.",
    version="4.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Request logging middleware
# ─────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start    = time.time()
    response = await call_next(request)
    elapsed  = round((time.time() - start) * 1000)
    log.info("%s %s → %d  [%dms]",
             request.method, request.url.path, response.status_code, elapsed)
    return response


# ─────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────

class Query(BaseModel):
    question: str
    language: str = "en"   # operator's UI language — used for response translation

class SessionRequest(BaseModel):
    session_id: str
    language:   str = "en"



# ─────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "AI Assistant v4"}


# ─────────────────────────────────────────────
# Transcribe: audio → text (+ translate to EN)
# ─────────────────────────────────────────────

@app.post("/transcribe")
async def transcribe(
    audio:    UploadFile = File(...),
    language: str        = Form(default="en"),
):
    """
    1. Transcribe audio with Whisper in the operator's language
    2. If Hindi/Gujarati, translate transcript to English for RAG
    3. Return both: English (for /ask) and original (for display)
    """
    audio_bytes = await audio.read()

    if len(audio_bytes) < 1000:
        raise HTTPException(status_code=400,
                            detail="Audio too short — nothing recorded.")

    result = transcribe_audio(audio_bytes, language=language)

    if not result["transcript"]:
        raise HTTPException(status_code=422,
                            detail="Could not transcribe audio. Please speak clearly.")

    transcript_original = result["transcript"]

    # Whisper always outputs Roman English script regardless of spoken language
    # so no translation needed at transcription time.
    # Translation only happens at answer time (en → hi/gu).
    return {
        "transcript":     transcript_original,
        "raw_transcript": result.get("raw_transcript", transcript_original),
        "language":       result["language"],
        "confidence":     result["confidence"],
    }


# ─────────────────────────────────────────────
# Ask: English question → RAG → translate answer
# ─────────────────────────────────────────────

@app.post("/ask")
def ask_question(query: Query):
    """
    Receives question in English (translated upstream by /transcribe or typed).
    Runs RAG on English manuals.
    Translates answer back to operator's language before returning.
    """
    if not query.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    lang   = query.language.lower()
    result = ask_rag(query.question)
    sources = result.get("sources", [])
    steps   = result.get("steps", [])

    def tr(text: str) -> str:
        if not text or not is_translation_needed(lang):
            return text
        out = from_english(text, to_lang=lang)
        log.info("Answer translated [en→%s]: %s → %s", lang, text[:50], out[:50])
        return out

    # ── Info mode ─────────────────────────────────────────────────────────
    if not is_procedure_query(query.question) or not steps:
        return {
            "mode":      "info",
            "answer":    tr(result["answer"]),
            "sources":   sources,
            "cache_hit": result.get("cache_hit", False),
            "llm_used":  result.get("llm_used", False),
        }

    # ── Procedure mode ────────────────────────────────────────────────────
    # Translate all steps at session creation time.
    # /next returns pre-translated steps so no per-step translation needed.
    translated_steps = [tr(s) for s in steps] if is_translation_needed(lang) else steps

    session_id = create_session(
        steps        = translated_steps,
        steps_detail = result.get("steps_detail", []),
        sources      = sources,
    )
    first_step = get_current_step(session_id)

    return {
        "mode":        "procedure",
        "session_id":  session_id,
        "step":        first_step,
        "sources":     sources,
        "total_steps": len(translated_steps),
        "cache_hit":   result.get("cache_hit", False),
        "llm_used":    result.get("llm_used", False),
    }


# ─────────────────────────────────────────────
# Next step
# ─────────────────────────────────────────────

@app.post("/next")
def get_next(req: SessionRequest):
    step = next_step(req.session_id)
    if step is None:
        return {"message": "Procedure completed", "session_id": req.session_id}
    return {"step": step, "session_id": req.session_id}


@app.get("/session/{session_id}")
def session_detail(session_id: str):
    summary = get_session_summary(session_id)
    if not summary:
        raise HTTPException(status_code=404,
                            detail="Session not found or already completed.")
    return summary




# ─────────────────────────────────────────────
# Cache admin
# ─────────────────────────────────────────────

@app.get("/cache/stats")
def cache_stats():
    return get_cache().stats()

@app.delete("/cache/clear")
def cache_clear():
    get_cache().clear()
    return {"message": "Cache cleared successfully."}
