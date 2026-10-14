# NOVA Learn AI — Production Deployment Guide

Deploy NOVA Learn AI using **Vercel** for the frontend, **Render** for the FastAPI backend, and **Neon** (or Render Postgres) for the PostgreSQL + pgvector database.

---

## Architecture Overview

```
┌─────────────────────────────────┐
│   Vercel (Frontend)             │
│   React + Vite + TypeScript     │
│   https://your-app.vercel.app   │
└────────────────┬────────────────┘
                 │ API calls (VITE_API_BASE_URL)
                 ▼
┌─────────────────────────────────┐
│   Render (Backend)              │
│   FastAPI + Uvicorn             │
│   https://your-api.onrender.com │
└────────────────┬────────────────┘
                 │ SQL / pgvector
                 ▼
┌─────────────────────────────────┐
│   Neon / Render PostgreSQL      │
│   PostgreSQL 16 + pgvector      │
└─────────────────────────────────┘
```

---

## Step 1: Database Setup (Neon or Render PostgreSQL)

### Option A: Neon (Free Serverless Postgres with pgvector) — Recommended
1. Go to [neon.tech](https://neon.tech) and create a free account.
2. Create a new project (e.g., `novalearn-db`).
3. Under the **SQL Editor**, enable the vector extension:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
4. Copy your **Connection string** (choose `Pooled connection` or `Direct connection`):
   ```text
   postgresql+psycopg://user:password@ep-xyz.region.neon.tech/neondb?sslmode=require
   ```
   *(Note: Ensure the driver prefix is `postgresql+psycopg://` for SQLAlchemy).*

### Option B: Render PostgreSQL
1. On [render.com](https://render.com), click **New +** → **PostgreSQL**.
2. Name it `novalearn-db`. Under Free tier, create the database.
3. In the Render shell or psql, run:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
4. Copy the **Internal Database URL** (or External URL). Replace `postgres://` with `postgresql+psycopg://`.

---

## Step 2: Deploy Backend on Render

1. Go to your [Render Dashboard](https://dashboard.render.com/) and click **New +** → **Web Service**.
2. Connect your GitHub repository: `Suraj-069/novalearn-ai`.
3. Choose one of the two deployment methods:

### Method 1: Docker (Recommended — includes FFmpeg & Tesseract OCR pre-installed)
- **Language / Runtime:** `Docker`
- **Docker Context / Build Context:** `backend`
- **Dockerfile Path:** `backend/Dockerfile`
- **Instance Type:** Free

### Method 2: Python Native
- **Runtime:** `Python`
- **Root Directory:** `backend`
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`

### Environment Variables on Render
Under **Environment Variables**, add:

| Key | Example Value | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://...` | Connection string from Step 1 |
| `JWT_SECRET` | `a_long_random_string_at_least_32_characters` | Secret for auth tokens |
| `CORS_ORIGINS` | `https://your-app.vercel.app,http://localhost:5173` | Allowed frontend domains (comma-separated) |
| `STORAGE_DIR` | `storage` | Uploaded documents directory |
| `LLM_PROVIDER` | `google` | Or `openai`, `anthropic`, `none` |
| `LLM_MODEL` | `gemini-3.5-flash-lite` | Or your chosen model |
| `LLM_API_KEY` | `AIzaSy...` | Your Gemini or provider API key |
| `EMBEDDING_PROVIDER` | `google` | Or `local-hash` |
| `EMBEDDING_MODEL` | `gemini-embedding-001` | 768-dimension embeddings |
| `EMBEDDING_API_KEY` | `AIzaSy...` | Your Gemini API key |

4. Click **Deploy Web Service**.
5. Once deployed, note your backend URL (e.g., `https://novalearn-api.onrender.com`).
6. Test it in your browser: `https://novalearn-api.onrender.com/api/health` should return `{"status":"ok",...}`.

---

## Step 3: Deploy Frontend on Vercel

1. Go to [vercel.com](https://vercel.com) and log in with your GitHub account.
2. Click **Add New...** → **Project**.
3. Import `Suraj-069/novalearn-ai`.
4. Configure the Project Settings:
   - **Framework Preset:** `Vite`
   - **Root Directory:** Click `Edit` and select `frontend`.
   - **Build Command:** `npm run build`
   - **Output Directory:** `dist`
5. In **Environment Variables**, add:

| Key | Value | Description |
|---|---|---|
| `VITE_API_BASE_URL` | `https://novalearn-api.onrender.com` | Your Render backend URL from Step 2 |

6. Click **Deploy**.
7. Vercel will build and launch your application (e.g. `https://novalearn-ai.vercel.app`).

---

## Step 4: Final CORS Sync

Now that you have your Vercel URL (e.g. `https://novalearn-ai.vercel.app`):
1. Return to your **Render Web Service** → **Environment Variables**.
2. Update `CORS_ORIGINS`:
   ```text
   https://novalearn-ai.vercel.app,http://localhost:5173
   ```
3. Click **Save Changes** (Render will automatically redeploy with the updated CORS policy).

---

## Verification Checklist

- [ ] Open frontend on Vercel (`https://your-app.vercel.app`).
- [ ] Register an account or sign in.
- [ ] Create a course and upload a PDF / slide deck.
- [ ] Check topic extraction in the **Knowledge** tab.
- [ ] Ask a grounded question in the **Tutor** chat.
- [ ] Click **Practice & Assessments** → **Generate and start** to verify quiz generation.
