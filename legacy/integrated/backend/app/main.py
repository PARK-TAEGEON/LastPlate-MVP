"""FastAPI application factory for the LastPlate Operation Agent."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.api.forecast_routes import router as forecast_router
from app.api.demo_routes import router as demo_router
from app.core.config import get_settings
from app.repositories import OperationPlanRepository
from app.services import OperationPlanService


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        repository = OperationPlanRepository(settings.database_path)
        repository.initialize()
        app.state.settings = settings
        app.state.operation_plan_service = OperationPlanService(repository)
        yield

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Forecast output + event changes + recipes + shared inventory -> "
            "safe cooking and purchasing recommendations."
        ),
        lifespan=lifespan,
    )
    # The MVP has no cookie/session authentication, so credentials are disabled.
    # Add the deployed frontend URL to LASTPLATE_CORS_ORIGINS before production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router)
    app.include_router(forecast_router)
    app.include_router(demo_router)
    frontend = Path(__file__).resolve().parents[2] / 'frontend'
    if frontend.is_dir():
        app.mount('/assets', StaticFiles(directory=frontend), name='assets')

        @app.get('/', include_in_schema=False)
        def index():
            return FileResponse(frontend / 'index.html')
    return app


app = create_app()
