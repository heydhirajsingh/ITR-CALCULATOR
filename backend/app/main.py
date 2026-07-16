"""FastAPI application factory and static frontend host."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.routes import router
from backend.app.database.session import SessionLocal, init_db
from backend.app.services.bootstrap_service import bootstrap

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    del app
    init_db()
    with SessionLocal() as db:
        bootstrap(db)
    yield


app = FastAPI(
    title="Local ITR Income Calculator",
    version="0.1.0",
    lifespan=lifespan,
    default_response_class=JSONResponse,
)
app.include_router(router)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    del request
    return JSONResponse(status_code=422, content={"detail": "Invalid input", "errors": exc.errors()})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return JSONResponse(status_code=500, content={"detail": "The operation failed safely.", "error": str(exc)})


if FRONTEND_DIST.exists():
    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):  # type: ignore[no-untyped-def]
        requested = FRONTEND_DIST / full_path
        if full_path and requested.exists() and requested.is_file():
            return FileResponse(requested)
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    async def missing_frontend() -> JSONResponse:
        return JSONResponse(
            {
                "message": "Frontend is not built. Run python main.py from the project root.",
                "api_docs": "/docs",
            }
        )
