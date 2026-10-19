"""Connection configuration and initial pricing, persisted in one transaction."""
from __future__ import annotations

import uuid

from app.core import config
from app.db import session
from app.integrations import openai_client
from app.schemas.gateway import ConnectionRequest

# Public gateway operations use the adapter implementation, not duplicate wrappers.
from app.integrations.openai_client import GatewayError, chat, test_connection


def connection() -> ConnectionRequest | None:
    with session.cursor() as cur:
        cur.execute('SELECT base_url, model, timeout_seconds, enabled FROM model_connection WHERE id = 1')
        row = cur.fetchone()
    return ConnectionRequest.model_validate(row) if row else None


def public_connection(value: ConnectionRequest | None) -> dict:
    return {'connection': value.model_dump() if value else None,
            'credential_configured': bool(openai_client.upstream_key()), 'runtime': config.laya_runtime()}


def save_connection(value: ConnectionRequest) -> dict:
    openai_client.check_credentials(value)
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
