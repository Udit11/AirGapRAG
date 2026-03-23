import uuid
import time
import threading
import logging

log = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 3600

_lock     = threading.Lock()
_sessions = {}


def _prune_expired():
    now     = time.time()
    expired = [sid for sid, s in _sessions.items()
               if now - s["last_active"] > SESSION_TTL_SECONDS]
    for sid in expired:
        log.info("Session %s expired and pruned.", sid)
        del _sessions[sid]


def create_session(steps, steps_detail=None, sources=None):
    session_id = str(uuid.uuid4())
    with _lock:
        _prune_expired()
        _sessions[session_id] = {
            "steps":        steps,
            "steps_detail": steps_detail or [],
            "sources":      sources or [],
            "current_step": 0,
            "created_at":   time.time(),
            "last_active":  time.time(),
        }
    log.info("Session %s created with %d steps.", session_id, len(steps))
    return session_id


def get_current_step(session_id):
    with _lock:
        session = _sessions.get(session_id)
        if not session:
            return None
        idx = session["current_step"]
        if idx >= len(session["steps"]):
            return None
        session["last_active"] = time.time()
        return {
            "step_number": idx + 1,
            "total_steps": len(session["steps"]),
            "text":        session["steps"][idx],
            "is_last":     idx + 1 == len(session["steps"]),
        }


def next_step(session_id):
    with _lock:
        session = _sessions.get(session_id)
        if not session:
            return None
        session["current_step"] += 1
        session["last_active"]  = time.time()
        idx = session["current_step"]
        if idx >= len(session["steps"]):
            log.info("Session %s completed.", session_id)
            del _sessions[session_id]
            return None
        return {
            "step_number": idx + 1,
            "total_steps": len(session["steps"]),
            "text":        session["steps"][idx],
            "is_last":     idx + 1 == len(session["steps"]),
        }


def get_session_summary(session_id):
    with _lock:
        session = _sessions.get(session_id)
        if not session:
            return None
        return {
            "session_id":   session_id,
            "total_steps":  len(session["steps"]),
            "current_step": session["current_step"] + 1,
            "sources":      session["sources"],
            "steps_detail": session["steps_detail"],
        }