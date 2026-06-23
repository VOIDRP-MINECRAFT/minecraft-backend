from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from apps.api.app.api.router import api_router
from apps.api.app.api.routes.rss import router as rss_router
from apps.api.app.config import get_settings
from apps.api.app.core.user_messages import format_validation_errors, translate_user_message


def create_app() -> FastAPI:
    settings = get_settings()

    os.makedirs(settings.media_storage_root, exist_ok=True)

    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        version="0.2.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_origin_regex=settings.cors_allow_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": format_validation_errors(exc.errors()),
                "errors": exc.errors(),
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(
        request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        detail = exc.detail

        if isinstance(detail, list):
            localized = format_validation_errors(detail)
            payload = {"detail": localized, "errors": detail}
        elif isinstance(detail, dict):
            errors = detail.get("errors") or detail.get("detail")
            if isinstance(errors, list):
                localized = format_validation_errors(errors)
                payload = {"detail": localized, "errors": errors}
            else:
                localized = translate_user_message(str(detail.get("detail") or detail.get("message") or ""))
                payload = {"detail": localized}
        else:
            payload = {"detail": translate_user_message(str(detail or ""))}

        return JSONResponse(status_code=exc.status_code, content=payload, headers=exc.headers)

    app.mount(
        settings.media_public_mount_path,
        StaticFiles(directory=settings.media_storage_root),
        name="media",
    )

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.include_router(rss_router)
    return app


app = create_app()
