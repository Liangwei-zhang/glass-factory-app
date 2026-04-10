from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from slowapi.errors import RateLimitExceeded
from slowapi.extension import _rate_limit_exceeded_handler

from apps.admin_api.routers import (
    acceptance,
    analytics,
    audit,
    health,
    operators,
    production_admin,
    runtime,
    tasks,
    users,
)
from infra.core.config import get_settings
from infra.core.context import clear_request_context, create_request_context, set_request_context
from infra.core.errors import register_exception_handlers
from infra.core.logging import configure_logging
from infra.http.response_envelope import should_wrap_success_response, wrap_success_response
from infra.observability.metrics import MetricsMiddleware
from infra.security.rate_limit import limiter

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging(debug=settings.debug)
    yield


app = FastAPI(
    title="Glass Factory Admin API",
    version="1.0.0",
    lifespan=lifespan,
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

    try:
        response = await call_next(request)
        if should_wrap_success_response(request.url.path, response):
            response = await wrap_success_response(response, context.request_id)
        response.headers["X-Request-ID"] = context.request_id
        return response
    finally:
        clear_request_context()


@app.get("/")
async def index() -> dict:
    return {
        "service": settings.app_name,
        "env": settings.app_env,
        "api": "admin",
        "prefix": settings.admin_api_prefix,
    }


app.include_router(health.router, prefix=settings.admin_api_prefix)
app.include_router(runtime.router, prefix=settings.admin_api_prefix)
app.include_router(analytics.router, prefix=settings.admin_api_prefix)
app.include_router(users.router, prefix=settings.admin_api_prefix)
app.include_router(operators.router, prefix=settings.admin_api_prefix)
app.include_router(audit.router, prefix=settings.admin_api_prefix)
app.include_router(tasks.router, prefix=settings.admin_api_prefix)
app.include_router(acceptance.router, prefix=settings.admin_api_prefix)
app.include_router(production_admin.router, prefix=settings.admin_api_prefix)
