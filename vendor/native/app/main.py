import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from integration import run_lastplate_pipeline,PipelineConfig
from integration.contracts import PipelineInput,PipelineResult

app=FastAPI(title='LastPlate advisory pipeline',version='0.1.2')

@app.exception_handler(RequestValidationError)
async def invalid_request(request,exc):
    result=PipelineResult(pipeline_status='FAILED',errors=[dict(stage='input',code='INPUT_VALIDATION_ERROR',http_status=422,kind='input',message=e['msg'],field=list(e['loc'])) for e in exc.errors()])
    return JSONResponse(status_code=422,content=result.model_dump(mode='json'))

def result_status(result):
    statuses=[e.get('http_status',500) for e in result['errors']]
    return 500 if any(s>=500 for s in statuses) else 409 if 409 in statuses else 422 if 422 in statuses else 200
@app.post('/api/plan')
def plan(payload:PipelineInput):
    cfg=dict(storage_dir=Path(os.environ.get('LASTPLATE_STORAGE','runtime')).resolve(),
        mode=os.environ.get('LASTPLATE_MODE','demo'))
    result=run_lastplate_pipeline(payload.model_dump(mode='json'),config=cfg)
    return JSONResponse(status_code=result_status(result),content=result)
