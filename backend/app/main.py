"""FastAPI application factory and entry point."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.dependencies import get_or_create_engine_and_factory
from app.api.v1.router import api_v1_router
from app.application.exceptions import ApplicationError
from app.config import Settings, get_settings
from app.decision import IllegalAgentToolCallError
from app.domain.exceptions import (
    DomainRuleViolationError,
    ImmutableRecordError,
    InvalidStateTransitionError,
    UnverifiedMasteryError,
)
from app.model_provider import ModelProviderError
from app.observability import RequestIdMiddleware
from app.persistence.migrations_runner import upgrade_database
from app.persistence.seed import import_content_pack, load_matching_headings_diagnostic_pack


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # In development mode, incrementally migrate schema to head and seed baseline content
        # without dropping existing tables or silently swallowing critical initialization errors.
        if resolved_settings.app_env == "development":
            engine, factory = get_or_create_engine_and_factory(resolved_settings)
            upgrade_database(database_url=resolved_settings.database_url, engine=engine)
            with factory() as session:
                try:
                    import_content_pack(session)
                    import_content_pack(
                        session,
                        pack_path=Path(__file__).parent / "content" / "ielts_reading_pack.json",
                    )
                    import_content_pack(
                        session,
                        pack_path=Path(__file__).parent / "content" / "ielts_reading_english_pack.json",
                    )
                    import_content_pack(
                        session,
                        pack_path=Path(__file__).parent / "content" / "ielts_tfng_diagnostic_pack.json",
                    )
                    import_content_pack(
                        session,
                        pack_data=load_matching_headings_diagnostic_pack(session),
                    )
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
        yield

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        description="VerbaTrail — evidence-based English learning system API",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # -----------------------------------------------------------------------
    # Exception Handlers
    # -----------------------------------------------------------------------

    @app.exception_handler(ApplicationError)
    async def application_error_handler(
        request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "req_unknown")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "request_id": request_id,
                "details": exc.details,
            },
        )

    @app.exception_handler(InvalidStateTransitionError)
    async def state_transition_error_handler(
        request: Request,
        exc: InvalidStateTransitionError,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "req_unknown")
        return JSONResponse(
            status_code=409,
            content={
                "code": "INVALID_STATE_TRANSITION",
                "message": str(exc),
                "request_id": request_id,
            },
        )

    @app.exception_handler(UnverifiedMasteryError)
    async def unverified_mastery_error_handler(
        request: Request,
        exc: UnverifiedMasteryError,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "req_unknown")
        return JSONResponse(
            status_code=400,
            content={
                "code": "UNVERIFIED_MASTERY",
                "message": str(exc),
                "request_id": request_id,
            },
        )

    @app.exception_handler(ImmutableRecordError)
    async def immutable_record_error_handler(
        request: Request,
        exc: ImmutableRecordError,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "req_unknown")
        return JSONResponse(
            status_code=403,
            content={
                "code": "IMMUTABLE_RECORD_VIOLATION",
                "message": str(exc),
                "request_id": request_id,
            },
        )

    @app.exception_handler(IllegalAgentToolCallError)
    async def illegal_agent_tool_error_handler(
        request: Request,
        exc: IllegalAgentToolCallError,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "req_unknown")
        return JSONResponse(
            status_code=400,
            content={
                "code": "ILLEGAL_AGENT_TOOL_CALL",
                "message": str(exc),
                "request_id": request_id,
            },
        )

    @app.exception_handler(DomainRuleViolationError)
    async def domain_rule_violation_handler(
        request: Request,
        exc: DomainRuleViolationError,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "req_unknown")
        return JSONResponse(
            status_code=400,
            content={
                "code": "DOMAIN_RULE_VIOLATION",
                "message": str(exc),
                "request_id": request_id,
            },
        )

    @app.exception_handler(ModelProviderError)
    async def model_provider_error_handler(
        request: Request,
        exc: ModelProviderError,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "req_unknown")
        status_code = 504 if "TIMEOUT" in exc.error_code else 502
        return JSONResponse(
            status_code=status_code,
            content={
                "code": exc.error_code,
                "message": exc.redacted_message,
                "request_id": request_id,
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "req_unknown")
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": f"HTTP_{exc.status_code}",
                "message": str(exc.detail),
                "request_id": request_id,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "req_unknown")
        return JSONResponse(
            status_code=422,
            content={
                "code": "VALIDATION_ERROR",
                "message": "请求参数校验失败",
                "request_id": request_id,
                "details": jsonable_encoder([
                    {key: value for key, value in error.items() if key not in {"ctx", "input"}}
                    for error in exc.errors()
                ]),
            },
        )

    app.include_router(api_v1_router, prefix=resolved_settings.api_v1_prefix)
    return app


app = create_app()
