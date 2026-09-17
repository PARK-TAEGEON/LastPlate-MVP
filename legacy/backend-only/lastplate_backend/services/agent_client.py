"""HTTP boundary only: preserve native payloads, partial results and HTTP status."""
import json
import httpx
from pydantic import ValidationError
from lastplate_backend.agent_contracts import AgentPipelineResult


class AgentServiceError(Exception):
    def __init__(self, code, message, status):
        super().__init__(message)
        self.code, self.status = code, status


class AgentClient:
    def __init__(self, base_url, timeout_seconds=600, *, transport=None):
        self.base_url = base_url
        self.client = httpx.Client(
            timeout=httpx.Timeout(timeout_seconds, connect=5, write=30, pool=5),
            follow_redirects=False, trust_env=False, transport=transport,
        )

    def close(self):
        self.client.close()

    def plan(self, payload):
        if not self.base_url:
            raise AgentServiceError('AGENT_SERVICE_NOT_CONFIGURED',
                'LASTPLATE_AGENT_BASE_URL에 별도 에이전트 서버 주소를 설정하세요.', 503)
        try:
            # Deliberately no automatic retries: upstream owns request_id semantics.
            response = self.client.post(self.base_url + '/api/plan', json=payload)
        except httpx.TimeoutException as exc:
            raise AgentServiceError('AGENT_SERVICE_TIMEOUT',
                '에이전트 응답 시간이 초과되었습니다. 처리 여부를 확인한 뒤 같은 request_id로 재시도하세요.', 504) from exc
        except httpx.RequestError as exc:
            raise AgentServiceError('AGENT_SERVICE_UNAVAILABLE',
                '별도 에이전트 서버에 연결할 수 없습니다. 주소와 실행 상태를 확인하세요.', 503) from exc
        if response.status_code not in (200, 409, 422, 500):
            raise AgentServiceError('AGENT_HTTP_PROTOCOL_ERROR',
                f'에이전트 API에서 계약과 다른 HTTP {response.status_code}를 반환했습니다.', 502)
        try:
            body = response.json()
            json.dumps(body, allow_nan=False)
            AgentPipelineResult.model_validate(body)
        except (ValueError, TypeError, ValidationError) as exc:
            raise AgentServiceError('AGENT_RESPONSE_INVALID',
                '에이전트 응답이 v0.1.2 PipelineResult 형식과 다릅니다. 서버 버전을 확인하세요.', 502) from exc
        # Return the original object, not the validated model dump: retain nulls,
        # unknown metadata, alerts, audit references and exact numeric values.
        return response.status_code, body
