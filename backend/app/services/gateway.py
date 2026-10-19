"""Connection configuration and initial pricing, persisted in one transaction."""
from __future__ import annotations

import uuid
from decimal import Decimal

from app.core import config
from app.db import session
from app.integrations import openai_client
from app.schemas.gateway import ConnectionRequest
from app.repositories import settings

# Public gateway operations use the adapter implementation, not duplicate wrappers.
from app.integrations.openai_client import GatewayError, chat, test_connection


def connection() -> ConnectionRequest | None:
    with session.read_session() as db:
        row = settings.connection(db)
    return ConnectionRequest.model_validate(row) if row else None


def public_connection(value: ConnectionRequest | None) -> dict:
    return {'connection': value.model_dump() if value else None,
            'credential_configured': bool(openai_client.upstream_key()), 'runtime': config.laya_runtime()}


def save_connection(value: ConnectionRequest) -> dict:
    openai_client.check_credentials(value)
    with session.unit_of_work() as db:
        settings.ensure_connection(db, value.base_url, value.model, value.timeout_seconds)
        settings.lock_connection(db)
        if settings.active_price(db, value.model) is None:
            settings.insert_initial_price(db, {
                'id': str(uuid.uuid4()), 'version': 'gw-' + uuid.uuid4().hex[:24], 'model': value.model,
                'currency': 'CNY', 'token_basis': 'upstream_prompt_tokens', 'unit_tokens': 1000000,
                'unit_price_yuan': Decimal('1.000000'), 'billing_policy_version': config.BILLING_POLICY_VERSION,
            })
        settings.update_connection(db, value.base_url, value.model, value.timeout_seconds, value.enabled)
    return public_connection(value)
