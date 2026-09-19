import os
import sys
from pathlib import Path

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from src.logger import setup_logging, logger
setup_logging()

from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.materials.routes import router as materials_router
from src.summary_generator.routes import router as summary_router
from src.rag.routes import router as tutor_router, ws_router
from src.quiz_generator.routes import router as quiz_router
from src.auth.routes import router as auth_router
from src.asr.routes import router as asr_router
from src.store import get_usage
from src.dependencies import get_current_user_id
from src.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from src.database import warmup_database
        warmup_database()
        logger.info("Local SQLite database ready.")
    except Exception as e:
        logger.warning(f"Database warmup failed: {e}")


    try:
        from src.rag.rag import get_embedder
        get_embedder()
        logger.info("Embedder loaded successfully.")
    except Exception as e:
        logger.warning(f"Embedder failed to load: {e}")

    from src.rag.batch_workers import start_workers
    start_workers()

    from src.asr.batch_workers import start_asr_workers
    start_asr_workers()

    yield



from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

app = FastAPI(
    title="AI Tutor API",
    description="Backend API for the AI Tutor for Students application",
    version="1.0.0",
    lifespan=lifespan,
)

_avatar_dir = Path(settings.sqlite_path).parent / "avatars"
_avatar_dir.mkdir(parents=True, exist_ok=True)
app.mount("/avatars", StaticFiles(directory=str(_avatar_dir)), name="avatars")

# When allow_credentials=True, browsers REJECT responses with "Access-Control-Allow-Origin: *"
# and refuse to store or send cookies. We must always use explicit origins.
_DEFAULT_ORIGINS = [
    "https://www.studybuddyai.dev",
    "https://studybuddyai.dev",
    "https://hamdy005-study-buddy.hf.space",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]
_raw_origins = settings.cors_allowed_origins if settings.cors_allowed_origins else _DEFAULT_ORIGINS
# Remove '*' if present to avoid browser credential rejection
_cors_origins = [o.strip() for o in _raw_origins if o.strip() and o.strip() != "*"] or _DEFAULT_ORIGINS

@app.middleware("http")
async def log_request_timing(request, call_next):
    import time
    start = time.perf_counter()
    # Fix double slashes in paths (e.g., //api/usage -> /api/usage)
    path = request.scope.get("path")
    if path and "//" in path:
        request.scope["path"] = path.replace("//", "/")
    response = await call_next(request)
    duration_sec = time.perf_counter() - start

    status = response.status_code
    if 200 <= status < 300:
        status_str = f"<green>{status}</green>"
    elif 300 <= status < 400:
        status_str = f"<cyan>{status}</cyan>"
    elif 400 <= status < 500:
        status_str = f"<red>{status}</red>"
    else:
        status_str = f"<bold><red>{status}</red></bold>"

    logger.opt(colors=True).info(f"{request.method} {request.url.path} - {status_str} ({duration_sec:.2f}s)")
    return response

app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# CORSMiddleware MUST be added LAST so it becomes the outermost layer in Starlette's middleware stack.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(materials_router)
app.include_router(summary_router)
app.include_router(tutor_router)
app.include_router(ws_router)
app.include_router(quiz_router)
app.include_router(auth_router)
app.include_router(asr_router)


@app.get("/")
async def root():
    return RedirectResponse(url="/docs")


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "AI Tutor API"}


@app.get("/api/usage")
async def get_user_usage(user_id: str = Depends(get_current_user_id)):
    return get_usage(user_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
