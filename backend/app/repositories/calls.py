"""Call lifecycle persistence, trusted receipts and user-scoped reservations."""
from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session
from app.models import ApiCall, ApiKey, InferenceSuccessReceipt, PricingRule, RequestIdempotency, UsageCharge


def _one(db: Session, statement) -> dict | None:
    row = db.execute(statement).mappings().first()
    return None if row is None else dict(row)


def lock_call(db: Session, call_id: str) -> dict | None:
    return _one(db, select(*ApiCall.__table__.columns).where(
        ApiCall.id == call_id).with_for_update())


def success_receipt(db: Session, call_id: str) -> dict | None:
    return _one(db, select(
        InferenceSuccessReceipt.input_tokens, InferenceSuccessReceipt.output_tokens,
        InferenceSuccessReceipt.truncated, InferenceSuccessReceipt.state_tokens_dropped,
        InferenceSuccessReceipt.completed_at, InferenceSuccessReceipt.duration_ms,
    ).where(InferenceSuccessReceipt.call_id == call_id))


def accept(db: Session, values: dict) -> None:
    # Execute immediately, in parent-key -> call order, before idempotency insertion.
    db.execute(update(ApiKey).where(ApiKey.id == values['api_key_id']).values(
        last_used_at=func.utc_timestamp(3)))
    db.execute(insert(ApiCall).values(**values, status='accepted', billing_status='pending',
        started_at=func.utc_timestamp(3), created_at=func.utc_timestamp(3), updated_at=func.utc_timestamp(3)))


def reserve(db: Session, user_id: str, key_hash: str, request_hash: str, call_id: str) -> None:
    db.execute(insert(RequestIdempotency).values(user_id=user_id, key_hash=key_hash,
        request_hash=request_hash, call_id=call_id, created_at=func.utc_timestamp(3)))


def reservation(db: Session, user_id: str, key_hash: str) -> dict | None:
    return _one(db, select(RequestIdempotency.call_id, RequestIdempotency.request_hash).where(
        RequestIdempotency.user_id == user_id, RequestIdempotency.key_hash == key_hash))


def mark_running(db: Session, call_id: str) -> int:
    return db.execute(update(ApiCall).where(ApiCall.id == call_id, ApiCall.status == 'accepted').values(
        status='running', updated_at=func.utc_timestamp(3))).rowcount


def capture_success(db: Session, call_id: str, values: tuple, duration_ms: int) -> None:
    db.execute(insert(InferenceSuccessReceipt).values(call_id=call_id,
        input_tokens=values[0], output_tokens=values[1], truncated=values[2],
        state_tokens_dropped=values[3], completed_at=func.utc_timestamp(3), duration_ms=duration_ms))


def settle(db: Session, call_id: str, values: dict, *, completed_at=None) -> None:
    db.execute(update(ApiCall).where(ApiCall.id == call_id).values(**values,
        completed_at=func.utc_timestamp(3) if completed_at is None else completed_at,
        updated_at=func.utc_timestamp(3)))


def keep_usage(db: Session, call_id: str, values: tuple) -> None:
    db.execute(update(ApiCall).where(ApiCall.id == call_id, ApiCall.input_tokens.is_(None)).values(
        input_tokens=values[0], output_tokens=values[1], truncated=values[2],
        state_tokens_dropped=values[3], updated_at=func.utc_timestamp(3)))


def inspect_calls(db: Session, limit: int, call_id: str | None, offset: int) -> list[dict]:
    c, r, h, p = ApiCall, InferenceSuccessReceipt, UsageCharge, PricingRule
    statement = select(
        c.id, c.status, c.http_status, c.error_code, c.billing_status, c.billing_reason,
        c.input_tokens, c.output_tokens, c.truncated, c.state_tokens_dropped, c.completed_at,
        c.duration_ms, c.started_at, c.model, c.pricing_rule_id, r.call_id.label('receipt_id'),
        r.input_tokens.label('r_input'), r.output_tokens.label('r_output'), r.truncated.label('r_truncated'),
        r.state_tokens_dropped.label('r_dropped'), r.completed_at.label('r_completed'),
        r.duration_ms.label('r_duration'), h.call_id.label('charge_id'), h.amount_yuan,
        h.pricing_rule_id.label('h_rule'), h.billable_input_tokens.label('h_input'),
        h.unit_tokens.label('h_unit'), h.unit_price_yuan.label('h_price'), h.currency.label('h_currency'),
        p.unit_tokens.label('p_unit'), p.unit_price_yuan.label('p_price'), p.currency.label('p_currency'),
        p.billing_policy_version.label('p_policy'), p.model.label('p_model'),
    ).outerjoin(r, r.call_id == c.id).outerjoin(h, h.call_id == c.id).outerjoin(p, p.id == c.pricing_rule_id)
    if call_id is not None:
        statement = statement.where(c.id == call_id)
    rows = db.execute(statement.order_by(c.started_at, c.id).limit(limit).offset(offset)).mappings().all()
    return [dict(row) for row in rows]
