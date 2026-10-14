# NOVA Learn AI — Devpost draft

## Problem

Students learn from disconnected lectures, slides, and textbooks, while generic chat assistants can give answers that are difficult to verify and do not adapt to a learner's demonstrated needs.

## Solution

NOVA Learn AI builds a course-scoped study companion. It indexes uploaded PDFs, slide decks, images, transcripts, and (when FFmpeg and an STT provider are configured) lecture video audio. The tutor retrieves course passages and returns citations that open their source locations. Assessments are source-associated and checked before delivery; submitted answers update transparent per-topic Bayesian Knowledge Tracing estimates.

## How it works

FastAPI, SQLAlchemy, Alembic, PostgreSQL/pgvector, React, Vite, and TypeScript support ingestion, hybrid search, tutoring, assessment, and analytics. OCR and optional vision descriptions preserve page/slide provenance. Hosted model capabilities require keys and are reported as unavailable when not configured.

## Challenges and what we learned

The difficult part is preserving provenance and refusing unsupported claims across extraction, retrieval, tutoring, and question generation. Deterministic checks improve traceability but do not establish pedagogical quality. BKT outputs are estimates with fixed, unfitted parameters.

## What's next

Choose and review a fixed licensed course benchmark, run the optional RAGAS evaluation against the configured provider, and validate the tutor and personalization with real learners. Synthetic adaptive-versus-random service-path simulation is implemented, but it does not establish real learning gains or human recommendation relevance. Add conversation-derived mastery evidence only with transparent, bounded rules.

## Evidence and submission fields to complete

This is a project description draft, not a claim that benchmark results or learning gains exist. Before submission, add the actual demo URL, public repository URL, team members' real names, and verified run results. No demo video, public repository URL, or team/Devpost submission details were available in this workspace.
