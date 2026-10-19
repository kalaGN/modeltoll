"""Read projections for tenant statistics and independent administrator totals."""

import datetime

from sqlalchemy import case, func, select, tuple_
from sqlalchemy.orm import Session

from app.models import ApiCall, ApiKey, PricingRule, UsageCharge, User


def _filters(user_id, start, end, api_key_id, endpoint):
    filters = [ApiCall.user_id == user_id, ApiCall.started_at >= start, ApiCall.started_at < end]
    if api_key_id:
        filters.append(ApiCall.api_key_id == api_key_id)
    if endpoint:
        filters.append(ApiCall.endpoint == endpoint)
    return filters


def _count_status(*statuses):
    # SUM(Boolean) otherwise inherits a Boolean result processor in SQLAlchemy.
    return func.sum(case((ApiCall.status.in_(statuses), 1), else_=0))


def usage_summary(db: Session, user_id, start, end, api_key_id, endpoint) -> tuple[dict, dict, dict]:
    filters = _filters(user_id, start, end, api_key_id, endpoint)
    calls = db.execute(select(
        func.count().label('total'), _count_status('succeeded').label('succeeded'),
        _count_status('failed', 'interrupted').label('failed'),
        _count_status('accepted', 'running').label('in_progress'),
        func.coalesce(func.sum(ApiCall.input_tokens), 0).label('input_tokens'),
        func.coalesce(func.sum(ApiCall.output_tokens), 0).label('output_tokens'),
    ).select_from(ApiCall).where(*filters)).mappings().one()
    charged = db.execute(select(
        func.count().label('billable_calls'),
        func.coalesce(func.sum(UsageCharge.billable_input_tokens), 0).label('billable_tokens'),
        func.coalesce(func.sum(UsageCharge.amount_yuan), 0).label('amount'),
    ).select_from(UsageCharge).join(ApiCall, ApiCall.id == UsageCharge.call_id)
        .where(*filters)).mappings().one()
    pending = db.execute(select(func.count().label('pending')).select_from(ApiCall)
        .where(*filters, ApiCall.billing_status == 'pending')).mappings().one()
    return dict(calls), dict(charged), dict(pending)


def _paged(statement, filters, after, size):
    if after:
        filters.append(tuple_(ApiCall.started_at, ApiCall.id) < tuple_(*after))
    return statement.where(*filters).order_by(ApiCall.started_at.desc(), ApiCall.id.desc()).limit(size)


def usage_calls(db: Session, user_id, start, end, api_key_id, endpoint, after, size) -> list[dict]:
    statement = select(
        ApiCall.id, ApiCall.endpoint, ApiCall.model, ApiCall.status, ApiCall.http_status,
        ApiCall.error_code, ApiCall.started_at, ApiCall.duration_ms, ApiCall.input_tokens,
        ApiCall.output_tokens, ApiCall.billing_status, ApiCall.billing_reason,
        ApiKey.display_prefix, ApiKey.last_four, PricingRule.version.label('pricing_version'),
    ).select_from(ApiCall).join(ApiKey, ApiKey.id == ApiCall.api_key_id).join(
        PricingRule, PricingRule.id == ApiCall.pricing_rule_id)
    rows = db.execute(_paged(statement, _filters(user_id, start, end, api_key_id, endpoint), after, size))
    return [dict(row) for row in rows.mappings()]


def billing_summary(db: Session, user_id, start, end, api_key_id, endpoint) -> dict:
    statement = select(
        func.coalesce(func.sum(UsageCharge.amount_yuan), 0).label('amount'),
        func.coalesce(func.sum(UsageCharge.billable_input_tokens), 0).label('tokens'),
        func.count().label('charges'),
    ).select_from(UsageCharge).join(ApiCall, ApiCall.id == UsageCharge.call_id)
    return dict(db.execute(statement.where(*_filters(user_id, start, end, api_key_id, endpoint)))
                .mappings().one())


def billing_charges(db: Session, user_id, start, end, api_key_id, endpoint, after, size) -> list[dict]:
    statement = select(
        ApiCall.id.label('call_id'), ApiCall.started_at, ApiKey.display_prefix, ApiKey.last_four,
        UsageCharge.billable_input_tokens, UsageCharge.unit_tokens, UsageCharge.unit_price_yuan,
        UsageCharge.amount_yuan, UsageCharge.currency, PricingRule.version.label('pricing_version'),
    ).select_from(UsageCharge).join(ApiCall, ApiCall.id == UsageCharge.call_id).join(
        ApiKey, ApiKey.id == ApiCall.api_key_id).join(PricingRule, PricingRule.id == UsageCharge.pricing_rule_id)
    rows = db.execute(_paged(statement, _filters(user_id, start, end, api_key_id, endpoint), after, size))
    return [dict(row) for row in rows.mappings()]


def daily_series(db: Session, user_id, start, end, api_key_id, endpoint) -> list[dict]:
    day = func.date(ApiCall.started_at)
    statement = select(
        day.label('day'), _count_status('succeeded').label('succeeded'),
        _count_status('failed', 'interrupted').label('failed'),
        func.coalesce(func.sum(ApiCall.input_tokens), 0).label('tokens'),
        func.coalesce(func.sum(UsageCharge.amount_yuan), 0).label('amount'),
    ).select_from(ApiCall).outerjoin(UsageCharge, UsageCharge.call_id == ApiCall.id)
    rows = db.execute(statement.where(*_filters(user_id, start, end, api_key_id, endpoint))
                      .group_by(day).order_by(day))
    return [dict(row) for row in rows.mappings()]


def platform_overview(db: Session, start: datetime.datetime, end: datetime.datetime) -> tuple[int, int, list[dict]]:
    users = db.execute(select(func.count()).select_from(User)).scalar_one()
    keys = db.execute(select(func.count()).select_from(ApiKey).join(User, User.id == ApiKey.user_id)
        .where(ApiKey.revoked_at.is_(None), ApiKey.deleted_at.is_(None), User.status == 'active')).scalar_one()
    day = func.date(ApiCall.started_at)
    rows = db.execute(select(day.label('day'), func.count().label('calls'),
        func.coalesce(func.sum(UsageCharge.amount_yuan), 0).label('amount'))
        .select_from(ApiCall).outerjoin(UsageCharge, UsageCharge.call_id == ApiCall.id)
        .where(ApiCall.started_at >= start, ApiCall.started_at < end).group_by(day).order_by(day))
    return users, keys, [dict(row) for row in rows.mappings()]
