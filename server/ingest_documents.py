import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import re
import faiss
import pickle
import pdfplumber
import logging
import numpy as np
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)

DOC_PATH   = "../data/documents"
STORE_PATH = "../vectorstore"

MAX_CHUNK_CHARS             = 2000
OVERLAP_CHARS               = 200
MIN_STEPS_FOR_PROCEDURE     = 1      # lower = catches more procedures

model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")


# ─────────────────────────────────────────────
# Heading and step patterns
# ─────────────────────────────────────────────

HEADING_RE = re.compile(
    r"^(\d+[\.\d]*\s+[A-Z][^\n]{3,80}"
    r"|[A-Z][A-Z\s\-]{5,60}$"
    r"|CHAPTER\s+\d+[^\n]{0,60})",
    re.MULTILINE
)

STEP_RE = re.compile(
    r"^\s*(\d+[\)\.]\s+|\([\da-z]\)\s+|step\s*\d+\s*[:\.]\s*)",
    re.IGNORECASE | re.MULTILINE
)


# ─────────────────────────────────────────────
# PDF reading
# ─────────────────────────────────────────────

def read_pdf(file_path):
    pages = []
    with pdfplumber.open(file_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if text and text.strip():
                pages.append((page_number, text))
    return pages


# ─────────────────────────────────────────────
# Procedure-aware chunking
# ─────────────────────────────────────────────

def detect_procedure_blocks(text):
    heading_matches = list(HEADING_RE.finditer(text))
    segments = []
    for i, m in enumerate(heading_matches):
        start = m.start()
        end = heading_matches[i + 1].start() if i + 1 < len(heading_matches) else len(text)
        segments.append((start, end, m.group(0).strip()))
    if not segments:
        segments = [(0, len(text), "")]
    blocks = []
    for start, end, heading in segments:
        segment_text = text[start:end].strip()
        if not segment_text:
            continue
        step_count = len(STEP_RE.findall(segment_text))
        block_type = "procedure" if step_count >= MIN_STEPS_FOR_PROCEDURE else "text"
        blocks.append({"type": block_type, "heading": heading,
                        "text": segment_text, "steps": step_count})
    return blocks


def chunk_procedure_block(block, source, page):
    text = block["text"]
    if len(text) <= MAX_CHUNK_CHARS:
        return [(text, {"source": source, "page": page,
                        "type": "procedure", "heading": block["heading"]})]
    step_positions = [m.start() for m in STEP_RE.finditer(text)]
    if not step_positions:
        return chunk_text_fixed(text, source, page,
                                block_type="procedure", heading=block["heading"])
    chunks = []
    current_start = 0
    for i in range(1, len(step_positions)):
        candidate = text[current_start:step_positions[i]]
        if len(candidate) > MAX_CHUNK_CHARS:
            chunk_content = text[current_start:step_positions[i - 1]].strip()
            if chunk_content:
                chunks.append((chunk_content,
                               {"source": source, "page": page,
                                "type": "procedure", "heading": block["heading"]}))
            current_start = step_positions[i - 1]
    remainder = text[current_start:].strip()
    if remainder:
        chunks.append((remainder,
                       {"source": source, "page": page,
                        "type": "procedure", "heading": block["heading"]}))
    return chunks if chunks else [(text[:MAX_CHUNK_CHARS],
                                   {"source": source, "page": page,
                                    "type": "procedure", "heading": block["heading"]})]


def chunk_text_fixed(text, source, page, block_type="text", heading=""):
    chunks = []
    start = 0
    while start < len(text):
        chunk = text[start:start + MAX_CHUNK_CHARS].strip()
        if len(chunk) > 50:
            chunks.append((chunk, {"source": source, "page": page,
                                   "type": block_type, "heading": heading}))
        start += MAX_CHUNK_CHARS - OVERLAP_CHARS
    return chunks


def chunk_document(pages, source):
    all_chunks = []
    for page_number, page_text in pages:
        blocks = detect_procedure_blocks(page_text)
        for block in blocks:
            if block["type"] == "procedure":
                chunks = chunk_procedure_block(block, source, page_number)
            else:
                chunks = chunk_text_fixed(block["text"], source, page_number,
                                          block_type="text", heading=block["heading"])
            all_chunks.extend(chunks)
    return all_chunks


# ─────────────────────────────────────────────
# Process all documents
# ─────────────────────────────────────────────

documents = []
metadata  = []

for file in sorted(os.listdir(DOC_PATH)):
    file_path = os.path.join(DOC_PATH, file)
    if file.endswith(".pdf"):
        log.info("Reading PDF: %s", file)
        pages  = read_pdf(file_path)
        chunks = chunk_document(pages, source=file)
        proc_count = sum(1 for _, m in chunks if m["type"] == "procedure")
        log.info("  → %d chunks (%d procedure blocks)", len(chunks), proc_count)
        for text, meta in chunks:
            documents.append(text)
            metadata.append(meta)
    elif file.endswith(".txt"):
        log.info("Reading TXT: %s", file)
        with open(file_path, "r", encoding="utf-8") as f:
            raw = f.read()
        chunks = chunk_document([(1, raw)], source=file)
        for text, meta in chunks:
            documents.append(text)
            metadata.append(meta)

log.info("Total chunks: %d", len(documents))

if not documents:
    log.error("No documents processed. Check PDF text extraction.")
    raise SystemExit(1)


# ─────────────────────────────────────────────
# Build FAISS index (cosine similarity)
# ─────────────────────────────────────────────

log.info("Generating embeddings (batch)...")
embeddings = model.encode(documents, batch_size=64, show_progress_bar=True)
embeddings = np.array(embeddings, dtype="float32")
faiss.normalize_L2(embeddings)

index = faiss.IndexFlatIP(embeddings.shape[1])
index.add(embeddings)


# ─────────────────────────────────────────────
# Build BM25 index
# ─────────────────────────────────────────────

log.info("Creating BM25 index...")
tokenized_corpus = [doc.lower().split() for doc in documents]
bm25 = BM25Okapi(tokenized_corpus)


# ─────────────────────────────────────────────
# Persist
# ─────────────────────────────────────────────

os.makedirs(STORE_PATH, exist_ok=True)

log.info("Saving FAISS index...")
faiss.write_index(index, os.path.join(STORE_PATH, "index.faiss"))

log.info("Saving documents & metadata...")
with open(os.path.join(STORE_PATH, "documents.pkl"), "wb") as f:
    pickle.dump((documents, metadata), f)

log.info("Saving BM25 index...")
with open(os.path.join(STORE_PATH, "bm25.pkl"), "wb") as f:
    pickle.dump(bm25, f)

with open(os.path.join(STORE_PATH, "tokenized_docs.pkl"), "wb") as f:
    pickle.dump(tokenized_corpus, f)

log.info("✅ Vector database + BM25 index created successfully")