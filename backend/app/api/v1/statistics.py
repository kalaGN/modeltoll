"""调用与费用统计查询。只返回当前登录用户名下的数据。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api import dependencies
from app.api.errors import http_error
from app.api.responses import success, utc_range
from app.schemas.statistics import StatsQuery
from app.services import accounts, model_runtime, statistics

router = APIRouter(tags=["statistics"])


def _range(query: StatsQuery):
    try:
        return statistics.parse_range(query.date_from, query.date_to)
    except statistics.StatsError as exc:
        raise http_error(exc.status_code, exc.code, exc.message) from None


def _query(
    date_from: str = Query(default="", alias="from"),
    date_to: str = Query(default="", alias="to"),
    api_key_id: str = "",
    endpoint: str = "",
    limit: int = 0,
    cursor: str = "",
) -> StatsQuery:
    return StatsQuery(date_from, date_to, api_key_id, endpoint, limit, cursor)


@router.get("/v1/usage/summary")
def usage_summary(
    user: accounts.User = Depends(dependencies.require_user),
    query: StatsQuery = Depends(_query),
):
    start, end = _range(query)
    totals = statistics.usage_summary(
        user.id, start, end, query.api_key_id, query.endpoint
    )
    return success(
        range=utc_range(start, end),
        totals=totals,
        series=statistics.daily_series(
            user.id, start, end, query.api_key_id, query.endpoint
        ),
    )


@router.get("/v1/usage/calls")
def usage_calls(
    user: accounts.User = Depends(dependencies.require_user),
    query: StatsQuery = Depends(_query),
):
    start, end = _range(query)
    page = statistics.usage_calls(
        user.id, start, end, query.api_key_id, query.endpoint, query.limit, query.cursor
    )
    return success(**{
        "range": utc_range(start, end),
        "limit": statistics.page_size(query.limit),
        **page,
    })


@router.get("/v1/billing/summary")
def billing_summary(
    user: accounts.User = Depends(dependencies.require_user),
    query: StatsQuery = Depends(_query),
):
    start, end = _range(query)
    totals = statistics.billing_summary(
        user.id, start, end, query.api_key_id, query.endpoint
    )
    return success(
        range=utc_range(start, end),
        price=statistics.current_price(model_runtime.MODEL_NAME),
        totals=totals,
        series=statistics.daily_series(
            user.id, start, end, query.api_key_id, query.endpoint
        ),
    )


@router.get("/v1/billing/charges")
def billing_charges(
    user: accounts.User = Depends(dependencies.require_user),
    query: StatsQuery = Depends(_query),
):
    start, end = _range(query)
    page = statistics.billing_charges(
        user.id, start, end, query.api_key_id, query.endpoint, query.limit, query.cursor
    )
    return success(**{
        "range": utc_range(start, end),
        "limit": statistics.page_size(query.limit),
        **page,
    })
