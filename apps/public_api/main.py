from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler

from apps.public_api.routers import (
    auth,
    customers,
    finance,
    health,
    inventory,
    legacy_api,
    logistics,
    monitoring,
    notifications,
    orders,
    production,
    search,
    ui,
)
from infra.core.config import get_settings
from infra.core.context import clear_request_context, create_request_context, set_request_context
from infra.core.errors import AppError, register_exception_handlers
from infra.core.logging import configure_logging, get_logger
from infra.db.session import init_models
from infra.http.response_envelope import should_wrap_success_response, wrap_success_response
from infra.observability.metrics import MetricsMiddleware
from infra.security.idempotency import enforce_idempotency_key
from infra.security.rate_limit import limiter

settings = get_settings()
PUBLIC_DIR = Path(__file__).resolve().parents[2] / "public"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging(debug=settings.debug)
    logger = get_logger()

    if settings.app_env == "dev" and settings.database.auto_init_schema_on_startup:
        try:
            await init_models()
            logger.info("Database schema initialized in dev mode")
        except Exception as exc:
            logger.warning("Skip schema init: {}", str(exc))

    yield


app = FastAPI(
    title="Glass Factory Public API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.state.limiter = limiter
register_exception_handlers(app)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(MetricsMiddleware)


@app.middleware("http")
async def attach_request_context(request: Request, call_next):
    context = create_request_context(
        trace_id=request.headers.get("traceparent"),
        user_ip=request.client.host if request.client else None,
    )
    set_request_context(context)
    request.state.request_id = context.request_id

    try:
        try:
            if request.url.path.startswith("/api") and request.method in {
                "POST",
                "PUT",
                "PATCH",
                "DELETE",
            }:
                namespace = f"legacy:{request.method.lower()}:{request.url.path}"
                await enforce_idempotency_key(namespace, request.headers.get("Idempotency-Key"))
        except AppError as exc:
            response = JSONResponse(status_code=exc.status_code, content=exc.to_payload())
            response.headers["X-Request-ID"] = context.request_id
            return response

        response = await call_next(request)
        if should_wrap_success_response(request.url.path, response):
            response = await wrap_success_response(response, context.request_id)
        response.headers["X-Request-ID"] = context.request_id
        return response
    finally:
        clear_request_context()


@app.get("/")
async def index() -> RedirectResponse:
    return RedirectResponse(url="/app", status_code=307)


app.include_router(health.router, prefix=settings.public_api_prefix)
app.include_router(auth.router, prefix=settings.public_api_prefix)
app.include_router(inventory.router, prefix=settings.public_api_prefix)
app.include_router(orders.router, prefix=settings.public_api_prefix)
app.include_router(monitoring.router, prefix=settings.public_api_prefix)
app.include_router(customers.router, prefix=settings.public_api_prefix)
app.include_router(production.router, prefix=settings.public_api_prefix)
app.include_router(logistics.router, prefix=settings.public_api_prefix)
app.include_router(finance.router, prefix=settings.public_api_prefix)
app.include_router(search.router, prefix=settings.public_api_prefix)
app.include_router(notifications.router, prefix=settings.public_api_prefix)
app.include_router(legacy_api.router)
app.include_router(ui.router)

if PUBLIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="public-static")
