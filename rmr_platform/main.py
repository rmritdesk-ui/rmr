from __future__ import annotations

import time
import os
from contextlib import asynccontextmanager
from collections import defaultdict, deque
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from . import __version__
from .config import settings
from .db import db_session
from .migrations import migrate, require_current_schema
from .models import User
from .seed import seed_demo, seed_reference_data
from .unified_seed import seed_unified_demo
from .security import current_user
from .routes import auth, campaigns, crm, forecast, onboarding, piq, portfolio, services, setup, solutions, system, training, unified, website
from .tenant_themes import router as tenant_themes_router, seed_tenant_themes
from . import client_admin_corrections, cumulative_product_repair, v53_experience, v531_final_corrections
from . import piq_worker, cb1_worker

BASE_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = BASE_DIR / "public"

@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.auto_migrate:
        migrate()
    else:
        require_current_schema()
    with db_session() as db:
        if settings.auto_seed:
            count = db.scalar(select(func.count(User.id))) or 0
            if count == 0:
                seed_demo(db, reset=False)
            seed_unified_demo(db)
            seed_tenant_themes(db)
    piq_worker_started = piq_worker.start() if settings.piq_worker_enabled else False
    cb1_worker_enabled = os.getenv("RMR_CB1_WORKER_ENABLED", "true").lower() == "true"
    if cb1_worker_enabled:
        cb1_worker.start()
    try:
        yield
    finally:
        if piq_worker_started:
            piq_worker.stop()
        if cb1_worker_enabled:
            cb1_worker.stop()


app = FastAPI(
    title="RMR Global",
    version=__version__,
    docs_url="/api/docs" if settings.environment != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Lightweight in-process rate limits for login and public lead endpoints. A
# distributed limiter can replace this when multiple app replicas are used.
_requests: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def security_and_rate_limit(request: Request, call_next):
    path = request.url.path
    if path in {"/api/auth/login", "/api/auth/password-reset/request", "/api/auth/password-reset/complete", "/api/auth/invitations/accept"} or path.startswith("/api/public/sites/"):
        key = f"{request.client.host if request.client else 'unknown'}:{path}"
        now = time.time()
        bucket = _requests[key]
        while bucket and bucket[0] < now - 60:
            bucket.popleft()
        if path == "/api/auth/login":
            limit = 12
        elif path.startswith("/api/auth/"):
            limit = 8
        else:
            limit = 30
        if len(bucket) >= limit:
            return JSONResponse(status_code=429, content={"detail": "Too many requests. Please try again shortly."})
        bucket.append(now)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-src 'self' https:; media-src 'self' https:;"
    )
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


for router in [
    setup.router,
    auth.router,
    portfolio.router,
    onboarding.router,
    services.router,
    crm.router,
    forecast.router,
    training.router,
    website.router,
    solutions.router,
    campaigns.router,
    piq.router,
    system.router,
    unified.router,
    client_admin_corrections.router,
    cumulative_product_repair.router,
    v53_experience.router,
    v531_final_corrections.router,
    tenant_themes_router,
]:
    app.include_router(router)

app.mount("/static", StaticFiles(directory=str(PUBLIC_DIR)), name="static")


@app.get("/api/training/files/{filename}")
def protected_training_file(filename: str, user=Depends(current_user)):
    safe_name = Path(filename).name
    path = settings.data_dir / "training" / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Training file not found")
    return FileResponse(path)


@app.get("/", include_in_schema=False)
def root():
    return FileResponse(PUBLIC_DIR / "index.html")



# Preserved commercial-correction services are registered before the SPA
# fallback so their API and owner console routes remain executable.
from rmr_platform.cb1_router import build_router as _build_cb1_router, install_cb1 as _install_cb1
_install_cb1(app)
app.include_router(_build_cb1_router(current_user))

from rmr_platform.commercial.router import router as commercial_router
from rmr_platform.commercial.middleware import restricted_data_middleware
app.include_router(commercial_router)
app.middleware("http")(restricted_data_middleware)

@app.get("/commercial-legacy", include_in_schema=False)
def rmr_commercial_console():
    return FileResponse(BASE_DIR / "static" / "commercial-console.html")


@app.get("/{path:path}", include_in_schema=False)
def spa_fallback(path: str):
    if path.startswith("api/") or path.startswith("sites/") or path.startswith("static/"):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(PUBLIC_DIR / "index.html")
