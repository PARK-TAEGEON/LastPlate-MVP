"""Standalone backend: no ML/agent module imports and no bundled frontend."""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from lastplate_backend.api.routes import router
from lastplate_backend.api.demo_routes import router as demo_router
from lastplate_backend.api.agent_routes import router as agent_router
from lastplate_backend.agent_contracts import failed_result
from lastplate_backend.core.config import get_settings
from lastplate_backend.repositories import OperationPlanRepository
from lastplate_backend.repositories.agent_plan_repository import AgentPlanRepository
from lastplate_backend.services import OperationPlanService
from lastplate_backend.services.agent_client import AgentClient


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        repository = OperationPlanRepository(settings.database_path)
        repository.initialize()
        app.state.settings = settings
        app.state.operation_plan_service = OperationPlanService(repository)
        app.state.agent_repository = AgentPlanRepository(settings.database_path)
        app.state.agent_repository.initialize()
        app.state.agent_client = AgentClient(settings.agent_base_url, settings.agent_timeout_seconds)
        try:
            yield
        finally:
            app.state.agent_client.close()

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan,
                  description='Operation backend and HTTP connection to a separately deployed agent service.')
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_credentials=False, allow_methods=['GET','POST'], allow_headers=['Content-Type'],
                       expose_headers=['X-LastPlate-Record-Id','X-LastPlate-Storage',
                                       'X-LastPlate-Upstream-Status','X-LastPlate-Error','Location'])
    app.include_router(router)
    app.include_router(demo_router)
    app.include_router(agent_router)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        if request.url.path == '/api/v1/agent-plans' and request.method == 'POST':
            result = failed_result('INPUT_VALIDATION_ERROR', '에이전트 API 입력 형식을 확인하세요.', 422, stage='input')
            result['errors'][0]['details'] = [dict(field=list(e['loc']), message=e['msg']) for e in exc.errors()]
            return JSONResponse(status_code=422, content=result)
        return await request_validation_exception_handler(request, exc)

    @app.get('/', include_in_schema=False)
    def index():
        return {'service':settings.app_name, 'version':settings.app_version, 'docs':'/docs',
                'frontend_bundled':False, 'model_bundled':False}

    return app


app = create_app()
