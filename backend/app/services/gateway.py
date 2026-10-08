"""固定上游和有限响应转发；不输出客户原文、凭据或上游错误正文。"""
from __future__ import annotations
import ipaddress
import json
import os
import uuid
from contextlib import nullcontext
from urllib.parse import urlsplit
import httpx
from app.core import config
from app.db import session
from app.schemas.gateway import ChatRequest, ConnectionRequest

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def _invalid_constant(value: str):
    raise ValueError('non-finite JSON number')


class GatewayError(Exception):
    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(code)
        self.code, self.message, self.status = code, message, status


def upstream_key() -> str:
    return os.environ.get('UPSTREAM_API_KEY', config.read_env_file().get('UPSTREAM_API_KEY', ''))


def check_credentials(value: ConnectionRequest) -> None:
    if not upstream_key() or urlsplit(value.base_url).scheme == 'https':
        return
    host = urlsplit(value.base_url).hostname
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == 'localhost'
    if not loopback:
        raise GatewayError('upstream_tls_required', '携带上游密钥时，非本机地址必须使用 HTTPS', 422)


def connection() -> ConnectionRequest | None:
    with session.cursor() as cur:
        cur.execute('SELECT base_url, model, timeout_seconds, enabled FROM model_connection WHERE id = 1')
        row = cur.fetchone()
    return ConnectionRequest.model_validate(row) if row else None


def public_connection(value: ConnectionRequest | None) -> dict:
    return {'connection': value.model_dump() if value else None,
            'credential_configured': bool(upstream_key()), 'runtime': config.laya_runtime()}


def save_connection(value: ConnectionRequest) -> dict:
    check_credentials(value)
    with session.transaction() as cur:
        cur.execute('INSERT IGNORE INTO model_connection (id, base_url, model, timeout_seconds, enabled, updated_at)'
                    ' VALUES (1, %s, %s, %s, 0, UTC_TIMESTAMP(3))', (value.base_url, value.model, value.timeout_seconds))
        cur.execute('SELECT id FROM model_connection WHERE id = 1 FOR UPDATE')
        cur.fetchone()
        cur.execute('SELECT id FROM pricing_rules WHERE model = %s AND effective_from <= UTC_TIMESTAMP(3) LIMIT 1', (value.model,))
        if cur.fetchone() is None:
            cur.execute("INSERT INTO pricing_rules (id, version, model, currency, token_basis, unit_tokens, unit_price_yuan,"
                        " billing_policy_version, effective_from, created_at) VALUES (%s, %s, %s, 'CNY',"
                        " 'upstream_prompt_tokens', 1000000, 1.000000, %s, UTC_TIMESTAMP(3), UTC_TIMESTAMP(3))",
                        (str(uuid.uuid4()), 'gw-' + uuid.uuid4().hex[:24], value.model, config.BILLING_POLICY_VERSION))
        cur.execute('UPDATE model_connection SET base_url = %s, model = %s, timeout_seconds = %s,'
                    ' enabled = %s, updated_at = UTC_TIMESTAMP(3) WHERE id = 1',
                    (value.base_url, value.model, value.timeout_seconds, value.enabled))
    return public_connection(value)


def _request(value: ConnectionRequest, path: str, body: dict | None = None,
             client: httpx.Client | None = None) -> dict:
    check_credentials(value)
    headers = {'Accept': 'application/json'}
    key = upstream_key()
    if key:
        headers['Authorization'] = 'Bearer ' + key
    timeout = httpx.Timeout(value.timeout_seconds, connect=min(5, value.timeout_seconds))
    manager = nullcontext(client) if client else httpx.Client(trust_env=False, follow_redirects=False)
    try:
        with manager as active:
            with active.stream('GET' if body is None else 'POST', value.base_url + path, json=body,
                               headers=headers, timeout=timeout, follow_redirects=False) as response:
                if response.status_code != 200:
                    raise GatewayError('upstream_error', '上游服务拒绝请求或返回错误，请检查管理员配置')
                data = bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise GatewayError('upstream_response_too_large', '上游响应超过 2 MB 限制')
                    data.extend(chunk)
        payload = json.loads(data, parse_constant=_invalid_constant)
        if not isinstance(payload, dict):
            raise ValueError('not an object')
        return payload
    except httpx.TimeoutException:
        raise GatewayError('upstream_timeout', '上游服务响应超时；本平台没有自动重试', 504) from None
    except (httpx.HTTPError, ValueError, RecursionError):
        raise GatewayError('upstream_invalid_response', '上游不可连接或返回无效 JSON') from None


def test_connection(value: ConnectionRequest) -> dict:
    payload = _request(value, '/models')
    rows = payload.get('data')
    if not isinstance(rows, list) or not any(isinstance(row, dict) and row.get('id') == value.model for row in rows):
        raise GatewayError('upstream_model_missing', '上游模型列表中不存在所配置的模型')
    return {'reachable': True, 'model': value.model}


def chat(value: ConnectionRequest, body: ChatRequest, client: httpx.Client | None = None) -> tuple[dict, dict]:
    payload = _request(value, '/chat/completions', body.model_dump(exclude_none=True), client)
    choices = payload.get('choices')
    if (not isinstance(payload.get('id'), str) or payload.get('object') != 'chat.completion' or
            payload.get('model') != value.model or not isinstance(choices, list) or not choices or
            any(not isinstance(row, dict) or not isinstance(row.get('message'), dict) or
                not isinstance(row['message'].get('content'), str) for row in choices)):
        raise GatewayError('upstream_invalid_response', '上游返回的 Chat Completions 结构无效')
    usage = payload.get('usage')
    prompt = usage.get('prompt_tokens') if isinstance(usage, dict) else None
    completion = usage.get('completion_tokens') if isinstance(usage, dict) else None
    if type(prompt) is not int or not 0 <= prompt <= 2**63 - 1 or (completion is not None and
            (type(completion) is not int or not 0 <= completion <= 2**63 - 1)):
        raise GatewayError('usage_unavailable', '上游未返回有效 Token 用量，本次未计费')
    return payload, {'input_tokens': prompt, 'output_tokens': completion}
