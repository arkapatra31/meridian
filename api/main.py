import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from db.database import dispose, init_db

from .routes import graphs, health, repos
from .routes.user_services import router as auth_router

_STATIC_DIR = Path(__file__).parent / "static"

load_dotenv()

logger = logging.getLogger("meridian.api")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = init_db()
    app.state.db_engine = engine
    try:
        yield
    finally:
        dispose()


def create_app() -> FastAPI:
    """FastAPI application factory."""
    app = FastAPI(
        title="Meridian API",
        version="0.1.0",
        description="Agent-powered code knowledge graph builder.",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    cors_origins = os.environ.get("MERIDIAN_CORS_ORIGINS", "*").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in cors_origins if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(auth_router)
    app.include_router(repos.router)
    app.include_router(graphs.router)

    if _STATIC_DIR.exists():
        app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str) -> FileResponse:
            return FileResponse(_STATIC_DIR / "index.html")

    return app


app = create_app()


def run() -> None:
    """Console entry point — `uv run python -m api.main`."""
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host=os.environ.get("MERIDIAN_HOST", "127.0.0.1"),
        port=int(os.environ.get("MERIDIAN_PORT", "8000")),
        reload=os.environ.get("MERIDIAN_RELOAD", "0") == "1",
    )


if __name__ == "__main__":
    run()
