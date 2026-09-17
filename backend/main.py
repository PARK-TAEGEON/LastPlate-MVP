import logging, sqlite3
from uuid import uuid4
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from backend.bootstrap import ROOT
from backend.settings import Settings
from backend.api.routes import router
from backend.api.workspace import router as workspace_router
from backend.api.access import developer_access
from backend.api.admin import router as admin_router
from backend.api.monthly import router as monthly_router
from fastapi.openapi.docs import get_swagger_ui_html
from backend.adapters.uploads import UploadError
from backend.adapters.persistence import Conflict
from lastplate_db import ValidationError as DatabaseValidationError


def failure(status,code,message,details=None):
    return JSONResponse(status_code=status,content={'pipeline_status':'FAILED',
        'request_id':uuid4().hex,'errors':[{'code':code,'message':message,'details':details or []}],
        'message':message})


class BodyLimit:
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        chunks=[];total=0
        while True:
            part=await receive()
            if part['type']=='http.disconnect':return
            total+=len(part.get('body',b''))
            if total>6*1024*1024:
                return await failure(413,'REQUEST_TOO_LARGE','요청은 6MB 이하로 보내주세요.')(scope,receive,send)
            chunks.append(part)
            if not part.get('more_body',False):break
        index=0
        async def replay():
            nonlocal index
            if index<len(chunks):
                value=chunks[index];index+=1;return value
            return await receive()
        return await self.app(scope,replay,send)


def create_app(settings=None):
    app=FastAPI(title='LastPlate Public API',version='1.0.0',docs_url=None,redoc_url=None,openapi_url=None,
        description='계산·위험·권고·운영 기록. 자동 발주·메뉴 변경·재학습 없음.')
    app.state.settings=settings or Settings.from_env()
    app.state.pending_runs={}
    app.add_middleware(BodyLimit)
    app.include_router(router)
    app.include_router(workspace_router)
    app.include_router(monthly_router)
    app.include_router(admin_router)

    async def validation(request,exc):
        details=[{'field':'.'.join(map(str,e['loc'])),'message':e['msg']} for e in exc.errors()]
        return failure(422,'INPUT_VALIDATION_ERROR','입력값 또는 필수 항목을 확인하세요.',details)
    app.add_exception_handler(RequestValidationError,validation)
    app.add_exception_handler(ValidationError,validation)

    @app.exception_handler(UploadError)
    async def upload_error(request,exc):return failure(422,exc.code,exc.message,exc.details)

    @app.exception_handler(Conflict)
    async def conflict(request,exc):return failure(409,'RECORD_CONFLICT',str(exc))

    @app.exception_handler(HTTPException)
    async def http_error(request,exc):
        response=failure(exc.status_code,'REQUEST_ERROR',str(exc.detail))
        if exc.headers:response.headers.update(exc.headers)
        return response

    @app.exception_handler(sqlite3.Error)
    @app.exception_handler(OSError)
    async def db_error(request,exc):
        logging.getLogger(__name__).exception('Database request failed')
        return failure(503,'PERSISTENCE_FAILED','데이터 저장소에 접근하지 못했습니다. 저장되지 않았습니다.')

    @app.exception_handler(DatabaseValidationError)
    async def data_error(request,exc):return failure(422,'PERSISTENCE_VALIDATION_ERROR','저장 데이터의 필수 항목 또는 출처를 확인하세요.')

    @app.exception_handler(Exception)
    async def server_error(request,exc):
        logging.getLogger(__name__).exception('Unhandled request error')
        return failure(500,'SERVER_ERROR','처리하지 못했습니다. 입력을 확인하거나 서버 로그의 오류를 확인하세요.')

    @app.get('/',include_in_schema=False)
    def index():return FileResponse(ROOT/'frontend/index.html',headers={'Cache-Control':'no-store'})
    @app.get('/debug',include_in_schema=False,dependencies=[Depends(developer_access)])
    def debug():return FileResponse(ROOT/'developer/index.html',headers={'Cache-Control':'no-store'})
    @app.get('/debug/app.js',include_in_schema=False,dependencies=[Depends(developer_access)])
    def debug_js():return FileResponse(ROOT/'developer/app.js')
    @app.get('/admin',include_in_schema=False,dependencies=[Depends(developer_access)])
    def admin():return FileResponse(ROOT/'developer/admin.html',headers={'Cache-Control':'no-store'})
    @app.get('/admin/app.js',include_in_schema=False,dependencies=[Depends(developer_access)])
    def admin_js():return FileResponse(ROOT/'developer/admin.js')
    @app.get('/openapi.json',include_in_schema=False,dependencies=[Depends(developer_access)])
    def openapi():return app.openapi()
    @app.get('/docs',include_in_schema=False,dependencies=[Depends(developer_access)])
    def docs():return get_swagger_ui_html(openapi_url='/openapi.json',title='LastPlate 개발자 API')
    @app.get('/favicon.ico',include_in_schema=False)
    def favicon():return FileResponse(ROOT/'frontend/favicon.svg',media_type='image/svg+xml')
    app.mount('/assets',StaticFiles(directory=ROOT/'frontend'),name='frontend')
    app.mount('/examples',StaticFiles(directory=ROOT/'examples'),name='examples')
    return app


app=create_app()
