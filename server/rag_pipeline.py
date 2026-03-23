import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import re
import faiss
import pickle
import requests
import numpy as np
import logging
from sentence_transformers import SentenceTransformer, CrossEncoder
from query_cache import SemanticQueryCache



logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)
log.info("Loading reranker model...")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_reranker = CrossEncoder(
    os.path.join(BASE_DIR, "ms-marco-MiniLM-L-6-v2"),
    device="cpu"
)
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)

STORE_PATH        = "../vectorstore"
LLM_URL           = "http://localhost:11434/api/generate"
LLM_MODEL         = "llama3.1:8b"
LLM_TIMEOUT       = 300

TOP_K_RETRIEVAL   = 20
TOP_K_FINAL       = 6
RRF_K             = 60
MAX_CONTEXT_CHARS = 4000
MIN_JACCARD       = 0.25
MIN_STEPS_TO_SKIP_LLM = 3


# ─────────────────────────────────────────────
# Load resources once at startup
# ─────────────────────────────────────────────

log.info("Loading embedding model...")
_model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")

log.info("Loading FAISS index...")
_index = faiss.read_index(os.path.join(STORE_PATH, "index.faiss"))

log.info("Loading documents & metadata...")
with open(os.path.join(STORE_PATH, "documents.pkl"), "rb") as f:
    _documents, _metadata = pickle.load(f)

log.info("Loading system prompt...")
with open("system_prompt.txt", "r", encoding="utf-8") as f:
    SYSTEM_PROMPT = f.read().strip()

log.info("Loading BM25 index...")
with open(os.path.join(STORE_PATH, "bm25.pkl"), "rb") as f:
    _bm25 = pickle.load(f)

log.info("Initialising semantic query cache...")
_cache = SemanticQueryCache(_model)

log.info("RAG system ready. %d chunks indexed.", len(_documents))


# ─────────────────────────────────────────────
# Query classification
# ─────────────────────────────────────────────

PROCEDURE_KEYWORDS = {
    "how", "procedure", "steps", "start", "dismantle", "remove",
    "install", "maintenance", "isolate", "replace", "overhaul",
    "assemble", "disassemble", "shutdown", "startup", "test",
    "inspect", "calibrate", "purge", "flush", "drain",
}


def is_procedure_query(question):
    q = question.lower()
    return any(kw in q for kw in PROCEDURE_KEYWORDS)


# ─────────────────────────────────────────────
# Reciprocal Rank Fusion
# ─────────────────────────────────────────────

def reciprocal_rank_fusion(rankings, k=RRF_K):
    scores = {}
    for ranked_list in rankings:
        for rank, doc_idx in enumerate(ranked_list, start=1):
            scores[doc_idx] = scores.get(doc_idx, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda i: scores[i], reverse=True)


# ─────────────────────────────────────────────
# Hybrid search
# ─────────────────────────────────────────────

def hybrid_search(query, top_k=TOP_K_RETRIEVAL):
    qvec = _model.encode([query]).astype("float32")
    faiss.normalize_L2(qvec)
    _, vector_indices = _index.search(qvec, top_k)
    vector_ranking = [int(i) for i in vector_indices[0] if i >= 0]

    tokenized_query = query.lower().split()
    bm25_scores     = _bm25.get_scores(tokenized_query)
    bm25_ranking    = sorted(range(len(bm25_scores)),
                             key=lambda i: bm25_scores[i], reverse=True)[:top_k]

    return reciprocal_rank_fusion([vector_ranking, bm25_ranking])

def rerank_documents(query, indices):
    """
    Takes document indices → reranks using CrossEncoder
    """
    docs = [_documents[i] for i in indices]

    pairs = [[query, doc] for doc in docs]
    scores = _reranker.predict(pairs)

    ranked = sorted(
        zip(indices, scores),
        key=lambda x: x[1],
        reverse=True
    )

    ranked_indices = [i for i, _ in ranked]
    ranked_scores  = [float(score) for _, score in ranked]

    return ranked_indices, ranked_scores

# ─────────────────────────────────────────────
# Procedure continuity expansion
# ─────────────────────────────────────────────

def expand_procedure_context(indices):
    expanded = list(indices)
    for i in indices:
        meta = _metadata[i]
        if meta.get("type") != "procedure":
            continue
        for neighbor in (i - 1, i + 1):
            if neighbor < 0 or neighbor >= len(_documents):
                continue
            n_meta = _metadata[neighbor]
            if (n_meta.get("source") == meta.get("source") and
                    n_meta.get("heading") == meta.get("heading") and
                    neighbor not in expanded):
                expanded.append(neighbor)
    return expanded


# ─────────────────────────────────────────────
# Context assembly
# ─────────────────────────────────────────────

PROCEDURE_TERMS = {
    "step", "procedure", "dismantling", "assembly", "installation",
    "removal", "inspection", "maintenance", "overhaul", "shutdown",
}


def retrieve_context(query, top_k=TOP_K_FINAL):
    candidates = hybrid_search(query)
    
    # 🔥 NEW: Reranking layer
    reranked_candidates, rerank_scores = rerank_documents(
        query,
        candidates[:TOP_K_RETRIEVAL]
    )

    candidates = reranked_candidates

    if is_procedure_query(query):
        boosted   = [i for i in candidates
                     if any(t in _documents[i].lower() for t in PROCEDURE_TERMS)]
        rest      = [i for i in candidates if i not in boosted]
        candidates = (boosted + rest)[:top_k * 2]

    candidates = expand_procedure_context(candidates[:top_k])
    candidates = sorted(set(candidates[:top_k]))

    context_parts = []
    sources        = []
    seen_sources   = set()
    total_chars    = 0

    for i in candidates:
        chunk   = _documents[i]
        meta    = _metadata[i]
        source  = meta.get("source", "Unknown")
        page    = meta.get("page", "Unknown")
        heading = meta.get("heading", "")
        ctype   = meta.get("type", "text")

        entry = (
            f"[Source: {source} | Page: {page}"
            + (f" | Section: {heading}" if heading else "")
            + f" | Type: {ctype}]\n{chunk}"
        )

        if total_chars + len(entry) > MAX_CONTEXT_CHARS:
            break

        context_parts.append(entry)
        total_chars += len(entry)

        src_key = (source, page)
        if src_key not in seen_sources:
            seen_sources.add(src_key)
            sources.append({"source": source, "page": page})

    return "\n\n---\n\n".join(context_parts), sources, rerank_scores[:len(candidates)]


# ─────────────────────────────────────────────
# Context-first step extraction
# ─────────────────────────────────────────────

def extract_steps_from_context(context):
    step_pattern = re.compile(
        r"(?:^|\n)\s*"
        r"(?:step\s*\d+\s*[:.\-]\s*|\d+[\).\s]+|\([a-z]\)\s+)"
        r"(.+?)(?=\n\s*(?:step\s*\d+|\d+[\).\s]+|\([a-z]\)\s+)|\Z)",
        re.IGNORECASE | re.DOTALL
    )
    matches = step_pattern.findall(context)
    steps = []
    for text in matches:
        clean = text.strip().replace("\n", " ")
        clean = re.sub(r"\s+", " ", clean)
        if len(clean) > 10 and not clean.isupper():
            steps.append(clean)
    return steps


# ─────────────────────────────────────────────
# LLM call
# ─────────────────────────────────────────────

def ask_llm(prompt):
    try:
        response = requests.post(
            LLM_URL,
            json={
                "model":  LLM_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": 280,
                    "temperature": 0.1,
                    "top_p":       0.9,
                }
            },
            timeout=LLM_TIMEOUT,
        )
        data = response.json()
        if "response" not in data:
            log.error("LLM returned no 'response' key: %s", data)
            return "Model did not return a valid response."
        return data["response"].strip()
    except requests.exceptions.Timeout:
        log.error("LLM timeout after %ds", LLM_TIMEOUT)
        return "ERROR: The AI model took too long to respond."
    except Exception as e:
        log.exception("LLM call failed")
        return f"ERROR: {e}"


# ─────────────────────────────────────────────
# Step extraction from LLM answer
# ─────────────────────────────────────────────

_STEP_PATTERN = re.compile(
    r"^(?:step\s*\d+\s*[:.\-]|\d+[.)]\s+|\([a-z]\)\s+)",
    re.IGNORECASE | re.MULTILINE,
)


def extract_steps_from_answer(answer):
    steps = []
    for line in answer.split("\n"):
        line = line.strip()
        if _STEP_PATTERN.match(line):
            clean = _STEP_PATTERN.sub("", line).strip()
            if len(clean) > 5:
                steps.append(clean)
    return steps


# ─────────────────────────────────────────────
# Hallucination guard (Jaccard token overlap)
# ─────────────────────────────────────────────

def _tokenize(text):
    return set(re.findall(r"\b\w+\b", text.lower()))


def jaccard_overlap(a, b):
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def verify_steps(steps, context):
    context_sentences = re.split(r"[.;\n]", context)
    verified = []
    for step in steps:
        best_score = max(
            (jaccard_overlap(step, sent) for sent in context_sentences),
            default=0.0,
        )
        verified.append({
            "text":       step,
            "verified":   best_score >= MIN_JACCARD,
            "confidence": round(best_score, 3),
        })
    return verified


# ─────────────────────────────────────────────
# Cache access (used by app.py for admin routes)
# ─────────────────────────────────────────────

def get_cache():
    return _cache


# ─────────────────────────────────────────────
# Main RAG function
# ─────────────────────────────────────────────
def compute_confidence(scores):
    if not scores:
        return 0.0
    return float(sum(scores) / len(scores))

def ask_rag(question):

    # ── Cache lookup ─────────────────────────────────────────────────
    cached = _cache.get(question)
    if cached:
        return cached

    # ── Retrieve context ─────────────────────────────────────────────
    context, sources, retrieval_scores = retrieve_context(question)

    # ── Fast path: extract steps directly from context ───────────────
    if is_procedure_query(question):
        context_steps = extract_steps_from_context(context)

        if len(context_steps) >= MIN_STEPS_TO_SKIP_LLM:
            log.info("Context-first extraction: %d steps found. LLM skipped.",
                     len(context_steps))

            verified_steps = verify_steps(context_steps, context)
            safe_steps     = [s["text"] for s in verified_steps if s["verified"]]

            answer_lines = [f"Step {i+1}: {s}" for i, s in enumerate(safe_steps)]
            answer = "\n".join(answer_lines)

            if sources:
                answer += f"\n\nSource: {sources[0]['source']}, Page {sources[0]['page']}"

            # 🔥 NEW: confidence for context-only path
            verification_conf = compute_confidence(
                [s["confidence"] for s in verified_steps]
            )

            retrieval_conf = compute_confidence(retrieval_scores) if retrieval_scores else 0.0

            confidence = 0.7 * verification_conf + 0.3 * retrieval_conf
            confidence = min(max(confidence, 0.0), 1.0)

            result = {
                "answer":       answer,
                "steps":        safe_steps,
                "steps_detail": verified_steps,
                "sources":      sources,
                "source":       sources[0]["source"] if sources else "Unknown",
                "page":         sources[0]["page"]   if sources else "Unknown",
                "context_used": context,
                "llm_used":     False,
                "cache_hit":    False,
                "confidence":   confidence,   # ✅ ADDED
            }

            _cache.store(question, result)
            return result

        log.info("Context-first extraction: only %d steps found. Falling back to LLM.",
                 len(context_steps))

    # ── Slow path: call LLM ──────────────────────────────────────────
    log.info("Calling LLM...")

    prompt = f"""{SYSTEM_PROMPT}

=== MAINTENANCE DOCUMENT CONTEXT ===
{context}
=== END OF CONTEXT ===

OPERATOR QUESTION:
{question}

INSTRUCTIONS:
- Answer ONLY from the context above.
- If the answer is a procedure, list every step in order:

Step 1: <exact action>
Step 2: <exact action>
...

- Do NOT invent, paraphrase, or add steps not present in the context.
- If the information is not in the context, reply exactly:
  "I cannot find this information in the maintenance documents."
- At the end, cite the source document and page number.

ANSWER:
"""

    answer         = ask_llm(prompt)
    raw_steps      = extract_steps_from_answer(answer)
    verified_steps = verify_steps(raw_steps, context)
    safe_steps     = [s["text"] for s in verified_steps if s["verified"]]

    # 🔥 NEW: confidence for LLM path
    verification_conf = compute_confidence(
        [s["confidence"] for s in verified_steps]
    )

    retrieval_conf = compute_confidence(retrieval_scores) if retrieval_scores else 0.0

    confidence = 0.7 * verification_conf + 0.3 * retrieval_conf
    confidence = min(max(confidence, 0.0), 1.0)

    result = {
        "answer":       answer,
        "steps":        safe_steps,
        "steps_detail": verified_steps,
        "sources":      sources,
        "source":       sources[0]["source"] if sources else "Unknown",
        "page":         sources[0]["page"]   if sources else "Unknown",
        "context_used": context,
        "llm_used":     True,
        "cache_hit":    False,
        "confidence":   confidence,   # ✅ ADDED
    }

    _cache.store(question, result)
    return result