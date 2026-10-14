import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import assessments, auth, courses, dashboard, documents, evaluation, knowledge, media, revision_cards, tutor, users
from app.core.config import get_settings
from app.services.providers.embeddings import validate_embedding_dimension

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # A real one-item probe catches missing credentials, unavailable models, and dimension drift
    # before requests can try to index or retrieve vectors. Cached for this process.
    validate_embedding_dimension()
    yield


def create_app() -> FastAPI:
    settings = get_settings()  # fails fast with a clear message if JWT_SECRET is missing
    app = FastAPI(title=f"{settings.app_name} API", version="0.4.0", description=settings.app_tagline, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,  # explicit origins only, never "*"
        allow_credentials=False,                  # bearer tokens, no cookies
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    for r in (auth.router, users.router, courses.router, documents.router, dashboard.router, knowledge.router, tutor.router, media.router, assessments.router, evaluation.router, revision_cards.router):
        app.include_router(r)

    @app.get("/api/health", tags=["meta"])
    def health():
        return {"status": "ok", "app": settings.app_name, "ai_provider_configured": settings.llm_provider != "none"}

    return app


app = create_app()
