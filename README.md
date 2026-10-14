# NOVA Learn AI â€” Learn smarter. Understand deeper.

A source-grounded personal study companion (Multimodal AI Hackathon 2026, Track D).

> **Current status: core learning workflows and in-app evaluation tools are implemented.** The Evaluation page runs source-labeled retrieval checks and seeded simulations over verified course questions.
> **No benchmark dataset or results are bundled.** The team must create and run a human-labeled test set for its course. The app's faithfulness and answer-relevancy scores use an in-project LLM rubric; the approved-case CLI separately supports optional RAGAS 0.4.3 metrics with Google Gemini. A timed walkthrough plan is at `docs/DEMO_SCRIPT.md`; no demo video has been recorded. A project description draft is at `docs/DEVPOST.md`. The UI does not invent evaluation outcomes.

## What works today (Stage 4 additions first)

- **Assessments:** quizzes, timed mock exams and a diagnostic, built from the selected topics, with multiple-choice, short-answer and (with a language model) numerical questions.
  - Every question carries a unique ID, topic tag, difficulty, type, source reference, answer key and explanation, and is **verified before it is offered** (answer must be supported by its source, exactly one correct option, distractors not stated in the source, formulas recomputed deterministically, optional second-model check that can only veto). Unverifiable candidates are rejected and counted. LLM prompts define difficulty by cognitive demand (recall, direct application, or multi-fact reasoning); offline difficulty remains a format ladder. The LLM difficulty calibration has a prompt-contract test, but its live quality is unverified.
  - **Never repeated:** new questions are compared with everything the student has already been given (exact text and embedding similarity); if the material runs out you are told, not shown repeats.
  - **Grading is deterministic by default:** exact match for multiple choice, tolerance for numbers, rubric concepts with partial credit for short answers. When an LLM is configured, it may add at most 0.25 partial credit for a source-consistent paraphrase of a missing short-answer concept; it must cite an exact quote from the student's answer, cannot remove deterministic credit or award full credit, and its rationale is shown. Provider errors use deterministic grading. Long answers do not receive LLM adjustments.
- **Learner model:** transparent Bayesian Knowledge Tracing per topic, separate from any LLM, appended to a persistent history with the evidence behind each update. A new student starts at a 20% prior, not an assumed level. Estimates are always labelled as estimates and show when they rest on few answers.
- **Personalisation:** quizzes weight topics toward your weakest estimates; recommendations (revisit a prerequisite, re-read the exact passage you missed, easier practice, challenge, spaced revision dates) are rule-based and each stores the numbers that triggered it; every result page proposes a personalised next quiz. The Dashboard can generate an exam-date plan from BKT estimates and export it as `.ics`; its displayed 14-day decay curve is a heuristic, not a fitted learner model.
- **Revision cards:** the Revise page reuses verified quiz questions and their source locations for topics with low mastery estimates. It does not invent cards when no verified, cited question is available.
- **Results and analytics:** score, per-topic performance, mastery before â†’ after, explanations with citations, inferred misconceptions (labelled "Inferred"), and real charts: mastery over time, assessment history, accuracy by difficulty, activity, strong/weak topics, upcoming revisions.
- **Optional voice:** the tutor offers browser speech input and read-aloud when the browser supports those APIs; typed questions and text answers remain available.

### Stage 3

- **Ingestion pipeline:** upload â†’ validate â†’ inspect â†’ extract text with provenance â†’ chunk â†’ embed â†’ index â†’ build topics, as a background job with live stage status, retry, and all-or-nothing indexing.
  - PDFs: text per page; scanned pages are read with OCR (Tesseract) and flagged as OCR. Substantial embedded images are indexed with page references; optional vision descriptions are labelled AI-written.
  - PowerPoint: text, tables, speaker notes per slide; substantial slide pictures via OCR and optional AI-written vision descriptions. Tiny/decorative images are filtered by size and slide-area thresholds.
  - Images: OCR and optional AI-written descriptions. Transcripts (`.vtt`/`.srt`): cues keep their exact timestamps. Video: FFmpeg audio extraction + speech-to-text with timestamps (needs an STT provider, see below).
- **Hybrid retrieval** (pgvector similarity + PostgreSQL full-text search, fused), always scoped to one course.
- **Source-grounded tutor:** answers come only from retrieved passages; every citation maps to a real stored passage and opens at the exact PDF page (rendered image + link to the page), slide (its text and notes), or video/transcript timestamp. If the material doesn't support an answer it says so instead of guessing. An optional, clearly labelled "general explanation" is available when a language model is configured. Conversations persist.
- **Knowledge explorer:** topics, subtopics, coverage by source, prerequisites, a concept map and list view. Rename topics, move passages, add/delete topics and prerequisites; your edits survive rebuilds.
  - Figure chunks show a source thumbnail and provenance. PDF and slide figure links are authorized with short-lived document-scoped media tokens. AI-written descriptions remain labelled; OCR and vision failures produce ingestion warnings. Assessment generation can use verified figure descriptions when an LLM is configured.
  - **Offline mode is available:** set `LLM_PROVIDER=none` and `EMBEDDING_PROVIDER=local-hash` for lexical embeddings and an *extractive* tutor. The setup template uses Grok for the LLM and Google AI Studio for semantic embeddings; provider calls are live only after you add your keys.

### Stage 2 foundation

- Sign up / sign in (bcrypt + JWT), onboarding (goals, explanation style, language, first course)
- Course create / rename / delete; upload PDF, `.pptx`, PNG/JPG/WebP, MP4/MOV/WebM/MKV, and `.vtt`/`.srt`/`.txt` transcripts
- Real validation (extension + file-content check + size limit), per-file status, retry, replace, delete, authenticated "open original"
- Inspection facts recorded from the real file: PDF pages and scanned-vs-text detection, slide count, video duration and audio-track check (needs FFmpeg), image size, transcript timestamp detection
- Dashboard, settings, data export, account deletion, responsive layout
- Per-user data isolation (other users get 404 for everything)

### Stage 5 evaluation

- **Retrieval and grounded-answer evaluation:** the course Evaluation screen takes questions labeled with a human-written reference answer and exact relevant source chunk IDs. Include off-material questions with `should_refuse: true` and no source IDs. Context precision uses mean average precision at the retrieval depth; context recall is the fraction of labeled chunk IDs retrieved; refusal accuracy checks the tutor's unsupported mode against the expected label.
- The app's faithfulness and answer relevancy use its configured language model as a single rubric judge. Separately, install `evaluation/requirements-ragas.txt` and pass `--ragas` to `run_rag_eval.py` to request RAGAS Context Precision, Context Recall, Faithfulness, and Answer Relevancy with Gemini. These are model estimates, not human judgments, and are reported separately from app metrics.
- **Personalization simulation:** the Evaluation page compares adaptive topic weighting with a uniform-random baseline on verified questions. The CLI additionally reads indexed course excerpts and exercises production assessment, attempt, grading, recommendation, and BKT services in disposable SQLite. It reports synthetic mastery gains and spread, BKT error, topic coverage, question repetition, and synthetic recommendation weak-topic precision; CLI data never reaches the configured database. Both simulations are synthetic and are not evidence that real students learned.
- Runs and per-case outputs use the existing evaluation tables. No team benchmark set or evaluation result is included; create and run a labeled test set before reporting scores.

### Preparing a reviewed evaluation test set

`evaluation/datasets/README.md` records why no benchmark data is bundled yet. After selecting a real, licensed course and starting the backend database, draft source-grounded questions (they remain unreviewed), manually approve/reject them, then validate source IDs:

```powershell
cd backend
python ..\evaluation\scripts\build_testset.py build COURSE_UUID --output ..\evaluation\datasets\draft.jsonl --limit 45
python ..\evaluation\scripts\build_testset.py add-refusal ..\evaluation\datasets\draft.jsonl "Ask a human-reviewed near-miss question here"
python ..\evaluation\scripts\build_testset.py review ..\evaluation\datasets\draft.jsonl
python ..\evaluation\scripts\build_testset.py validate ..\evaluation\datasets\draft.jsonl
```

Drafting needs a configured LLM. A valid benchmark requires at least 20% human-approved off-material refusal cases; the builder does not invent or auto-approve those. For a reviewed dataset, log in to the app, set the returned access token and run:

```powershell
$env:NOVA_ACCESS_TOKEN = "<access-token>"
python ..\evaluation\scripts\run_rag_eval.py --course-id COURSE_UUID --dataset ..\evaluation\datasets\approved.jsonl
```

The command posts approved cases through the app's real retrieval/tutor evaluator and writes timestamped JSON and Markdown under `evaluation/reports/`. Metrics include in-project context precision/recall, single-model-judge faithfulness/relevancy, citation accuracy, hit@k/MRR, refusal accuracy, and false-refusal/false-acceptance rates. A fixed approved team dataset is not included. To additionally run the optional RAGAS metrics using Gemini, install `evaluation/requirements-ragas.txt` and add `--ragas`; details are in [`evaluation/README.md`](evaluation/README.md). No external-framework result is bundled.

## Requirements

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11+ (tested 3.12) | |
| Node.js | 20+ (tested 22) | |
| PostgreSQL with pgvector | 16 recommended | Easiest via Docker (below) |
| FFmpeg | any recent | Videos: duration check and audio extraction |
| Tesseract OCR | 5.x | Scanned PDFs and images. Without it, those files fail with a clear message |

## Setup on Windows (PowerShell, VS Code terminal)

### 1. Database (Docker Desktop)

```powershell
docker compose up -d db
```

This starts PostgreSQL 16 with pgvector on port 5432 (user/password/db: `nova`/`nova`/`novalearn`). Wait until `docker compose ps` reports the database as `healthy`. If you prefer a native install, install pgvector and give the DB user permission to run `CREATE EXTENSION vector`.

### 2. Environment file

```powershell
copy .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the generated value after `JWT_SECRET=` in `.env`. The template uses Google AI Studio Gemini for tutoring and embeddings: add the same AI Studio key to `LLM_API_KEY` and `EMBEDDING_API_KEY`; do not commit `.env`. It selects `gemini-3.5-flash-lite` for the LLM and `gemini-embedding-001` at 768 dimensions. This configuration passed the real provider, topic/prerequisite, numerical-generation, and deterministic-verification checks on 2026-10-14. To use xAI Grok instead, set `LLM_PROVIDER=xai`, select a model available to your xAI account, and put that account's key in `LLM_API_KEY`. To run offline without a key, set `LLM_PROVIDER=none`, `EMBEDDING_PROVIDER=local-hash`, clear the model/key settings, and restart the backend.

### 3. Backend

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs Â· Health: http://localhost:8000/api/health

If PowerShell blocks activation: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### 4. Frontend (second terminal)

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The dev server proxies `/api` to port 8000.

## Setup on Linux (Bash)

Use Docker Engine with the Compose plugin, Python 3.11 or newer, and Node.js 20 or newer. Run these commands from the repository root unless a `cd` is shown.

```bash
docker compose up -d db
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Put the generated value in `JWT_SECRET` in `.env`. Set the xAI Grok key in `LLM_API_KEY` and the Google AI Studio key in `EMBEDDING_API_KEY`. The backend intentionally refuses startup if the selected embedding provider cannot be reached or its output does not match the schema. To use offline mode, set `LLM_PROVIDER=none` and `EMBEDDING_PROVIDER=local-hash` in `.env`.

In terminal 1, install and start the backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

In terminal 2, start the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite development server proxies `/api` to the backend on port 8000. Install FFmpeg and Tesseract separately if you need video processing or OCR; see the optional dependencies section below.

On Ubuntu or Debian, install those optional system tools with:

```bash
sudo apt update
sudo apt install ffmpeg tesseract-ocr
```

### 5. FFmpeg and Tesseract (optional but recommended)

```powershell
winget install Gyan.FFmpeg
winget install UB-Mannheim.TesseractOCR
```

Restart the terminal, then check `ffprobe -version` and `tesseract --version`. Add Tesseract's install folder (usually `C:\Program Files\Tesseract-OCR`) to `PATH` if the second command isn't found. For other OCR languages set `OCR_LANGUAGE` (e.g. `eng+hin`) and install that language data.

### 6. Verify real providers

The backend checks the configured embedding model during startup with one small embedding request. With a hosted provider, this is a real API call. Startup stops with a clear error if the provider is unreachable, credentials are missing, or the returned vector doesn't match `EMBEDDING_DIM` and the current `vector(768)` schema. The Grok adapter uses xAI's OpenAI-compatible Chat Completions API; Gemini embeddings use Google's `batchEmbedContents` endpoint and requested 768-dimensional vectors. Automated tests cover their request and response shapes. STT is disabled in this two-provider configuration.

From `backend/`, run the live provider and learning-feature smoke checks:

```powershell
python scripts/check_providers.py
```

This makes a small real chat request, embedding request, then checks LLM topic/prerequisite extraction and generates a numerical assessment question through the existing verification gate using temporary SQLite data. If timestamped speech-to-text is enabled, supply a short speech file (this project currently leaves STT disabled):

```powershell
python scripts/check_providers.py --audio .\sample.wav
```

Linux equivalent (run from `backend/`):

```bash
python scripts/check_providers.py
python scripts/check_providers.py --audio ./sample.wav
```

Without an LLM key or semantic embedding model, the script reports a failure instead of treating offline behavior as a real-provider pass. STT is skipped when not configured. Grok/Google keys are not used for STT; the current two-provider setup leaves it disabled.

| Capability | Setting | Notes |
|---|---|---|
| Written explanations | `LLM_PROVIDER=google` (template), `xai`, or `none` offline; `LLM_MODEL`, `LLM_API_KEY`, optional `LLM_BASE_URL` | The template uses the live-verified `gemini-3.5-flash-lite`; `gemini-3.1-flash-lite` also passed. Provider availability and quota can change. The LLM adapter handles text, JSON mode, and vision descriptions |
| Semantic search | `EMBEDDING_PROVIDER=google` (or `local-hash` offline), `EMBEDDING_MODEL`, `EMBEDDING_API_KEY`, optional `EMBEDDING_BASE_URL` | The template uses Google `gemini-embedding-001` requested at 768 dimensions. Startup probes the actual output. The current schema is fixed at vector(768); changing it needs a migration and re-indexing |
| Video speech-to-text | STT is disabled in the current Grok + Google configuration. Upload a `.vtt`/`.srt` transcript instead |
| Figure descriptions | `VISION_ENABLED=true` + a vision-capable LLM | Descriptions are labelled "AI-written" everywhere |

After changing the embedding model, delete and re-upload files (or use Retry on each) so every passage is re-embedded.

### Running Stage 5 evaluations

CLI tools draft source-grounded items as unreviewed, support explicit human review, add manually authored refusal cases, and validate accepted chunk IDs. The repository still has no fixed human-reviewed benchmark dataset. After approval, `run_rag_eval.py` sends only approved JSONL through the live app evaluator and writes JSON/Markdown reports. Its optional `--ragas` mode separately computes RAGAS Context Precision, Context Recall, Faithfulness, and Answer Relevancy from actual outputs and contexts with Gemini; these are model estimates, not human judgments. Neither mode claims independent human review.

1. Upload and index course files. For personalization, create an assessment first so the course has verified questions.
2. Open the course and choose **Evaluation**. Search the source list and copy a real chunk ID into an answerable test case's `relevant_chunk_ids`.
3. Paste a JSON array into the retrieval form. Each answerable case needs `question`, a human-checked `reference_answer`, one or more `relevant_chunk_ids`, and `should_refuse: false`. Each off-material case needs `reference_answer: null`, an empty source list, and `should_refuse: true`.
4. Run the evaluation and inspect saved metrics, retrieved IDs, tutor outputs, sample counts, and unavailable reasons. The API accepts up to 50 cases per run. It does not create ground truth or pre-populate scores.
5. Run a personalization simulation with five or more sessions. It compares adaptive and uniform-random topic selection across five seeded runs by default. The default profiles define independent hidden skill, slip, guess, learning, and forgetting rates.

To save a standalone simulation artifact set, run this from `backend/` after indexing topic-tagged course source excerpts:

```powershell
python scripts/run_simulation.py --course-id COURSE_UUID --runs 5 --sessions 5 --questions-per-session 3
```

The script copies source excerpts into a disposable in-memory SQLite database and exercises production assessment creation/verification, attempt submission, grading, recommendation, and BKT services. It writes timestamped JSON, Markdown, and PNG files under `evaluation/reports/`; adaptive/random outcomes are synthetic, not real student results. Mastery gain is measured from the pre-session hidden-mastery baseline through the final session; the per-session report shows cumulative change from that same baseline. It fails when the source material cannot produce verified questions; it does not create placeholder reports or write simulation rows to the configured database. The latest run used 5 sessions, 3 questions per session, 5 repeated runs, 4 profiles, and 161 course excerpts: [`simulation-20261014T131012Z.md`](evaluation/reports/simulation-20261014T131012Z.md).

See [`evaluation/README.md`](evaluation/README.md) for the test-case contract and metric definitions. A team-authored dataset is not included because the repository does not contain human-verified answer and source labels.

## Tests

Backend (SQLite; no running services needed):

```powershell
cd backend
.venv\Scripts\Activate.ps1
pytest -q
```

On Linux, activate with `source .venv/bin/activate` before running `pytest -q`. To run the suite against PostgreSQL + pgvector, first create `novalearn_test` and enable the vector extension if needed, then set `TEST_DATABASE_URL`:

```powershell
$env:TEST_DATABASE_URL="postgresql+psycopg://nova:nova@localhost:5432/novalearn_test"
pytest -q
```

```bash
TEST_DATABASE_URL="postgresql+psycopg://nova:nova@localhost:5432/novalearn_test" pytest -q
```

Frontend, from `frontend/`: `npm run typecheck` and `npm run build`.

### Current verification

Current workspace recheck (2026-10-14): Docker Compose PostgreSQL/pgvector was healthy on port 5432. On a newly created isolated empty database, Alembic `upgrade head` -> `downgrade base` -> `upgrade head` completed at `0003 (head)`; Uvicorn started after a real Gemini embedding dimension probe returned HTTP 200. The current API and Vite homepage returned HTTP 200. Backend: **213 passed, 3 skipped in 220.30 seconds**. Frontend `npm run typecheck` and `npm run build` passed; Vite reported a 731.12 kB minified JavaScript chunk warning.

Latest real provider smoke checks (`backend/scripts/check_providers.py`):
- Embeddings: **PASS** (`gemini-embedding-001`, 768 dimensions, 928 ms).
- The previous `gemini-3.8-flash` setting returned HTTP 429/503. The local `.env` now uses the tested `gemini-3.5-flash-lite`; the API key was not changed.
- `python scripts/check_providers.py --model gemini-3.5-flash-lite`: **4 passed, 0 failed** (LLM completion 1,909 ms; embeddings 928 ms; topic extraction produced 3 topics and 2 prerequisite links in 1,469 ms; numerical generation produced one question that passed 8 deterministic checks in 4,163 ms).
- STT is not configured.
- RAGAS integration is implemented, but its optional dependency and live evaluation have not been run. The latest synthetic service-path run used 161 excerpts across 9 Computer Network topics: [`simulation-20261014T131012Z.md`](evaluation/reports/simulation-20261014T131012Z.md), with JSON and PNG alongside it. The report records 600 synthetic assessments/attempts and 600 mastery events across both arms; results are not a team-reviewed RAG benchmark or real-student evidence. No team-reviewed benchmark, external-framework results, or real-student learning results are bundled.

Provider diagnostic: Google's `generateContent` REST endpoint, headers (`x-goog-api-key`), `systemInstruction`, and `generationConfig` conform to Google's official REST specification. The adapter filters internal thinking tokens (`not part.get("thought")`) and extracts Google error detail messages cleanly. Account quota and model demand are managed upstream in Google AI Studio.

## Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `JWT_SECRET` | **Required**, 32+ chars |
| `DATABASE_URL` | SQLAlchemy URL, default points at the Docker DB |
| `CORS_ORIGINS` | Comma-separated allowed origins |
| `STORAGE_DIR` | Upload root; relative paths resolve from the project root |
| `MAX_DOCUMENT_MB` / `MAX_VIDEO_MB` | Upload size caps (100 / 1024) |
| `LLM_*`, `EMBEDDING_*`, `STT_PROVIDER` | Grok and Google AI Studio are selected in `.env.example`; configure both keys before starting. Set `LLM_PROVIDER=none`, `EMBEDDING_PROVIDER=local-hash` for offline operation |

Rename the product or recolour it: `frontend/src/components/Logo.tsx` (`BRAND`), `frontend/tailwind.config.js` (palette), `APP_NAME` in `.env`.

## Troubleshooting

- **"JWT_SECRET is missingâ€¦"** â€” create `.env` in the project root and set it.
- **`could not connect to server`** â€” start the DB (`docker compose ps`), check `DATABASE_URL`.
- **`extension "vector" is not available`** â€” your PostgreSQL lacks pgvector; use the Docker image.
- **Embedding startup check fails** â€” verify the provider, model and API key. The migration fixes storage at 768 dimensions; Google `gemini-embedding-001` is requested at 768 dimensions. Apply a schema migration and re-index before selecting another dimension.
- **Frontend shows "Can't reach the server"** â€” backend isn't running on port 8000.
- **Port 5432 in use** â€” stop a local PostgreSQL, or change the port mapping and `DATABASE_URL`.
- **Video shows an FFmpeg warning** â€” install FFmpeg and restart the terminal.
- **Legacy `.ppt` rejected** â€” re-save as `.pptx`.

## Known limitations

- Auth token is stored in `localStorage` (prototype trade-off); no email verification or password reset.
- Auth rate limiting is in-memory, single process.
- No virus scanning of uploads.
- Public video URLs are not supported; upload the file or a transcript.
- `.ppt` and Word files are not supported.
- Offline embeddings match **words, not meaning** (no synonyms); the tutor compensates by refusing when the question's key words aren't in the material. Use a hosted/Ollama embedding model for real semantic search.
- Without a language model, topic names are keywords ("Entropy & Heat"), topics are flat, and **no prerequisite links are generated** (add them yourself or configure an LLM).
- Not implemented yet: PDF table extraction, analysis of video frames/slides shown in a lecture, linking an uploaded transcript to its video, and streaming (token-by-token) answers. Substantial embedded PDF/PPTX figures are extracted with OCR and optional LLM descriptions; video keyframes are not analyzed.
- **Offline question quality is basic.** Without a language model, questions are fill-in-the-blank built from one sentence of your material, and "difficulty" is a format ladder (easy = multiple choice, medium = one blank, hard = two blanks), not conceptual depth. Distractors are other terms from your course, so some are weak. Numerical questions need a language model. Add one in `.env` for richer questions; its output still passes the same verification.
- **Verification has limits.** It proves a question's answer is in the source and the options are distinct; it cannot prove a model-written question is *good* or that a plausible distractor isn't arguably right. The optional second-model check is an extra filter, not a guarantee.
- Short-answer grading is a keyword rubric (with stemming): it can be gamed by listing terms (long answers are capped) and cannot judge reasoning.
- Mastery uses fixed, conservative, unfitted BKT parameters. Early estimates (fewer than 3 answers) are volatile and labelled "early". Nothing here shows that it improves learning.
- Unanswered questions score zero and give no mastery evidence; an assessment can be taken once (retakes would reward memorising).
- Slide citations show the slide's extracted text and notes, not a pixel render (no PowerPoint renderer is bundled).
- A transcript cited without its video shows the timestamp only; a *video* citation plays from the right second.

## Project layout

See `docs/ARCHITECTURE.md`. Short version: `backend/` (FastAPI, SQLAlchemy, Alembic), `frontend/` (Vite, React, TypeScript, Tailwind), `evaluation/` (evaluation case format and metric definitions), `storage/` (uploads), `docs/`.
