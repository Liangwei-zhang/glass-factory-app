from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler

from apps.public_api.routers import (
    auth,
    customer_app,
    customers,
    finance,
    health,
    inventory,
    logistics,
    monitoring,
    notifications,
    orders,
    production,
    search,
    ui,
    workspace,
)
from infra.core.config import get_settings
from infra.core.context import clear_request_context, create_request_context, set_request_context
from infra.core.errors import register_exception_handlers
from infra.core.logging import configure_logging, get_logger
from infra.db.dev_bootstrap import ensure_dev_demo_users
from infra.db.session import init_models
from infra.http.response_envelope import should_wrap_success_response, wrap_success_response
from infra.observability.metrics import MetricsMiddleware
from infra.security.rate_limit import limiter

settings = get_settings()
PUBLIC_DIR = Path(__file__).resolve().parents[2] / "public"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging(debug=settings.debug)
    logger = get_logger()

    if settings.app_env == "dev":
        try:
            if settings.database.auto_init_schema_on_startup:
                await init_models()
                logger.info("Database schema initialized in dev mode")

            seeded_users = await ensure_dev_demo_users()
            if seeded_users:
                logger.info("Seeded dev demo users count={}", seeded_users)
        except Exception as exc:
            logger.warning("Skip dev bootstrap: {}", str(exc))

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
app.include_router(customer_app.router, prefix=settings.public_api_prefix)
app.include_router(production.router, prefix=settings.public_api_prefix)
app.include_router(logistics.router, prefix=settings.public_api_prefix)
app.include_router(finance.router, prefix=settings.public_api_prefix)
app.include_router(search.router, prefix=settings.public_api_prefix)
app.include_router(notifications.router, prefix=settings.public_api_prefix)
app.include_router(workspace.router, prefix=settings.public_api_prefix)
app.include_router(ui.router)

if PUBLIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="public-static")
