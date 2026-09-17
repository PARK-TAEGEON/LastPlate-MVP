"""Diagnostic / original integration API access is opt-in and authenticated."""
import secrets
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials

basic=HTTPBasic(auto_error=False)

def developer_access(request:Request, credentials:HTTPBasicCredentials|None=Depends(basic)):
    settings=request.app.state.settings
    if not settings.debug_enabled or not settings.debug_token:
        raise HTTPException(404,'개발자 도구가 꺼져 있습니다.')
    if not credentials:
        raise HTTPException(401,'개발자 인증이 필요합니다.',headers={'WWW-Authenticate':'Basic realm="LastPlate developer"'})
    user_ok=secrets.compare_digest(credentials.username.encode(),b'developer')
    token_ok=secrets.compare_digest(credentials.password.encode(),settings.debug_token.encode())
    if not (user_ok and token_ok):
        raise HTTPException(401,'개발자 인증이 필요합니다.',headers={'WWW-Authenticate':'Basic realm="LastPlate developer"'})

def legacy_access(request:Request, credentials:HTTPBasicCredentials|None=Depends(basic)):
    if request.url.path=='/api/health':return
    return developer_access(request,credentials)
