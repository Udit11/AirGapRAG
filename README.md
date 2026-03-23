# AirGapRAG 🚀
### Air-Gapped, Hallucination-Controlled RAG System for Industrial Maintenance Manuals

> **Production-ready retrieval for environments where the internet is not an option — and wrong answers are not acceptable.**

[![GitHub](https://img.shields.io/badge/GitHub-AirGapRAG-1A3A5C?style=flat&logo=github)](https://github.com/Udit11/AirGapRAG.git)

---

## Overview

AirGapRAG is a fully offline Retrieval-Augmented Generation (RAG) system engineered for industrial facilities operating in air-gapped or internet-restricted environments. It retrieves accurate, step-by-step maintenance procedures directly from indexed PDF manuals — with no cloud dependency, no API calls, and no hallucinated answers.

Designed for real deployment, not proof-of-concept demos.

---

## Why This Project Matters

Most GenAI systems are not viable in industrial settings because they:

- Require internet connectivity and third-party API access
- Hallucinate plausible-sounding but incorrect procedures
- Offer no traceability or source attribution

AirGapRAG is built around three non-negotiable properties:

- **Deterministic retrieval** — results are reproducible and grounded in indexed documents
- **Full traceability** — every response includes its source document and page reference
- **Offline-first architecture** — runs entirely on local hardware with no external dependencies

---

## Key Features

| Feature | Description |
|---|---|
| Fully Offline | Air-gapped ready — no internet, no API keys, no cloud |
| Procedure Extraction | Structured step-by-step answers pulled directly from manuals |
| Hallucination-Controlled (Strict Retrieval Boundaries) | Hard fallback: refuses to answer if information is not found in indexed documents |
| Hybrid Retrieval | FAISS semantic search + BM25 keyword search for maximum recall |
| Cross-Encoder Reranking | Precision reranking via `ms-marco-MiniLM-L-6-v2` |
| Local Model Deployment | Runs entirely on-premise on standard hardware |
| Session Tracking | Maintains procedure state across multi-turn queries |

---

## Architecture

```
User Query
   ↓
Embedding Search (FAISS)
   ↓
Keyword Search (BM25)
   ↓
Reranking (Cross-Encoder)
   ↓
Context Selection
   ↓
Step Extraction / Controlled LLM Fallback
   ↓
   (LLM is only used when structured extraction fails and is constrained to retrieved context)
   ↓
Structured Response with Source
```

---

## Tech Stack

| Component | Tool |
|---|---|
| Language | Python |
| Web Framework | FastAPI |
| Embeddings | SentenceTransformers (`all-MiniLM-L6-v2`) |
| Reranking | Cross-Encoder (`ms-marco-MiniLM-L-6-v2`) |
| Vector Store | FAISS |
| Keyword Search | BM25 |
| PDF Parsing | pdfplumber |
| Frontend | Vanilla JavaScript |

---

## Project Structure

```
AirGapRAG/
├── client/
├── data/
│   └── documents/
├── server/
│   ├── app.py
│   ├── rag_pipeline.py
│   ├── ingest_documents.py
│   ├── system_prompt.txt
│   ├── session_manager.py
│   ├── query_cache.py
│   └── llm_engine.py
├── README.md
└── .gitignore
```

---

## Setup

### 1. Clone the Repository

```bash
git clone https://github.com/Udit11/AirGapRAG.git
cd AirGapRAG
```

### 2. Install Dependencies

```bash
pip install -r server/requirements.txt
```

### 3. Add Documents

Place PDF maintenance manuals inside:

```
data/documents/
```

### 4. Build Vector Database

```bash
python server/ingest_documents.py
```

### 5. Run the Backend

```bash
uvicorn server.app:app --reload
```

### 6. Open the Frontend

Open directly in your browser:

```
client/index.html
```

---

## Example Output

**Query:** `What is the stopping procedure for the hydraulic press?`

**Response:**

```
Stopping Procedure — Hydraulic Press

Step 1: Set the control lever to the NEUTRAL position.
Step 2: Allow the system pressure to drop below 10 bar before proceeding.
Step 3: Engage the manual lockout valve on the hydraulic supply line.
Step 4: Power off the motor using the main disconnect switch.
Step 5: Verify that all moving components have come to a complete stop.
Step 6: Attach the lockout/tagout (LOTO) device before performing any maintenance.

Source: Hydraulic Press Maintenance Manual v3.2, Page 47
```

If the information is not found in any indexed document, the system responds:

```
I cannot find this information in the maintenance documents.
```

No inference. No guessing. No fabricated steps.

---

## Demo

> Screenshot / screen recording coming soon.
>
> To evaluate locally, run the setup steps above and query against your own PDF manuals.

---

## Hallucination Control

AirGapRAG enforces a strict answer boundary. The system will not generate an answer from general knowledge or model weights — responses are produced only when sufficient context is retrieved from indexed documents. Every answer includes a traceable source reference.

This makes it suitable for safety-critical maintenance workflows where procedural accuracy is non-negotiable.

---

## Author

**Udit Srivastava**  
AI/ML Engineer — RAG, LLM Systems, Industrial AI  
[github.com/Udit11/AirGapRAG](https://github.com/Udit11/AirGapRAG.git)
