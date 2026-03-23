import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import pickle
import threading
import logging
import numpy as np
from datetime import datetime

log = logging.getLogger(__name__)

CACHE_PATH       = "../vectorstore/query_cache.pkl"
SIMILARITY_THRESHOLD = 0.92   # cosine similarity — tune down to 0.88 if too few hits
MAX_CACHE_SIZE   = 500        # max entries before oldest are evicted


class SemanticQueryCache:
    """
    Disk-persisted semantic cache for RAG query results.

    On each lookup:
      1. Encode the incoming question into an embedding.
      2. Compute cosine similarity against all cached question embeddings.
      3. If best match >= SIMILARITY_THRESHOLD, return cached result instantly.
      4. Otherwise return None (caller proceeds to full RAG pipeline).

    On each store:
      1. Add question embedding + result to in-memory cache.
      2. Flush to disk immediately.
    """

    def __init__(self, embedding_model):
        self._model   = embedding_model
        self._lock    = threading.Lock()

        # Each entry: {"question": str, "embedding": np.array, "result": dict, "ts": str}
        self._entries = []

        self._load()

    # ─────────────────────────────────────────
    # Persistence
    # ─────────────────────────────────────────

    def _load(self):
        if os.path.exists(CACHE_PATH):
            try:
                with open(CACHE_PATH, "rb") as f:
                    self._entries = pickle.load(f)
                log.info("Query cache loaded: %d entries.", len(self._entries))
            except Exception as e:
                log.warning("Could not load cache file, starting fresh. Error: %s", e)
                self._entries = []
        else:
            log.info("No existing query cache found. Starting fresh.")
            self._entries = []

    def _flush(self):
        """Write current cache to disk. Call while holding the lock."""
        try:
            os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
            with open(CACHE_PATH, "wb") as f:
                pickle.dump(self._entries, f)
        except Exception as e:
            log.error("Failed to flush cache to disk: %s", e)

    # ─────────────────────────────────────────
    # Cosine similarity
    # ─────────────────────────────────────────

    @staticmethod
    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        denom = (np.linalg.norm(a) * np.linalg.norm(b))
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)

    # ─────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────

    def get(self, question: str):
        """
        Returns cached result dict if a semantically similar question
        was seen before, otherwise returns None.
        """
        if not self._entries:
            return None

        q_emb = self._model.encode([question])[0].astype("float32")

        with self._lock:
            best_score = -1.0
            best_entry = None

            for entry in self._entries:
                score = self._cosine(q_emb, entry["embedding"])
                if score > best_score:
                    best_score = score
                    best_entry = entry

            if best_score >= SIMILARITY_THRESHOLD:
                log.info(
                    "Cache HIT (similarity=%.4f) for: '%s' → matched: '%s'",
                    best_score, question, best_entry["question"]
                )
                # Return a copy so callers cannot mutate the cache
                result = dict(best_entry["result"])
                result["cache_hit"]         = True
                result["cache_similarity"]  = round(best_score, 4)
                result["cache_matched_q"]   = best_entry["question"]
                return result

            log.info("Cache MISS (best similarity=%.4f) for: '%s'", best_score, question)
            return None

    def store(self, question: str, result: dict):
        """
        Store a question + its result in the cache and flush to disk.
        Evicts the oldest entry if MAX_CACHE_SIZE is reached.
        """
        q_emb = self._model.encode([question])[0].astype("float32")

        # Strip non-serialisable / bulky fields before caching
        cacheable = {k: v for k, v in result.items()
                     if k not in ("context_used",)}

        entry = {
            "question":  question,
            "embedding": q_emb,
            "result":    cacheable,
            "ts":        datetime.now().isoformat(),
        }

        with self._lock:
            # Evict oldest if at capacity
            if len(self._entries) >= MAX_CACHE_SIZE:
                evicted = self._entries.pop(0)
                log.info("Cache full. Evicted oldest entry: '%s'", evicted["question"])

            self._entries.append(entry)
            self._flush()

        log.info("Cache stored (%d entries total): '%s'", len(self._entries), question)

    def clear(self):
        """Wipe the entire cache from memory and disk."""
        with self._lock:
            self._entries = []
            self._flush()
        log.info("Query cache cleared.")

    def stats(self):
        """Return cache statistics for the /cache/stats API endpoint."""
        with self._lock:
            return {
                "total_entries":      len(self._entries),
                "max_size":           MAX_CACHE_SIZE,
                "similarity_threshold": SIMILARITY_THRESHOLD,
                "cache_path":         CACHE_PATH,
                "entries": [
                    {
                        "question": e["question"],
                        "cached_at": e["ts"],
                    }
                    for e in self._entries
                ],
            }