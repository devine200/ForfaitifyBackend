"""Period cashflow and interest series derived from posted ledger rows."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Sum
from django.utils import timezone

from balances.models import BalanceTransaction

PERIOD = timedelta(days=30)
SUCCESS = BalanceTransaction.Status.SUCCESSFUL


def _sum(qs) -> int:
    return qs.aggregate(s=Sum("amount_cents"))["s"] or 0


def flow(user, types: list[str], start, end) -> int:
    return _sum(
        BalanceTransaction.objects.filter(
            balance__user=user,
            type__in=types,
            status=SUCCESS,
            created_at__gte=start,
            created_at__lt=end,
        )
    )


def percent_change(current: int, previous: int) -> str:
    if previous == 0:
        if current == 0:
            return "0%"
        return "+100%" if current > 0 else "-100%"
    pct = (current - previous) / previous * 100
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.1f}%"


def period_bounds(now=None):
    now = now or timezone.now()
    current_start = now - PERIOD
    previous_start = current_start - PERIOD
    return now, current_start, previous_start


def earning_streak_months(user) -> int:
    now = timezone.now()
    stamps = BalanceTransaction.objects.filter(
        balance__user=user,
        type=BalanceTransaction.Type.RETURN,
        status=SUCCESS,
        created_at__gte=now - timedelta(days=800),
    ).values_list("created_at", flat=True)
    months = {(stamp.year, stamp.month) for stamp in stamps}
    year, month = now.year, now.month
    streak = 0
    while (year, month) in months:
        streak += 1
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return streak


def _dollars(cents: int) -> float:
    return round(cents / 100, 2)


def _shift_months(moment, months: int):
    index = moment.month - 1 + months
    year = moment.year + index // 12
    month = index % 12 + 1
    return moment.replace(year=year, month=month, day=1)


def interest_series_for(qs) -> dict[str, list[dict]]:
    """Weekly, monthly, and yearly return totals. Values are dollars."""
    now = timezone.now()
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = week_start - timedelta(weeks=7)
    weekly = []
    for i in range(8):
        start = week_start + timedelta(weeks=i)
        end = start + timedelta(weeks=1)
        weekly.append(
            {
                "label": start.strftime("%b %d"),
                "value": _dollars(_sum(qs.filter(created_at__gte=start, created_at__lt=end))),
            }
        )

    month_anchor = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    first_month = _shift_months(month_anchor, -5)
    monthly = []
    for i in range(6):
        start = _shift_months(first_month, i)
        end = _shift_months(start, 1)
        monthly.append(
            {
                "label": start.strftime("%b %Y"),
                "value": _dollars(_sum(qs.filter(created_at__gte=start, created_at__lt=end))),
            }
        )

    yearly = []
    for year in range(now.year - 3, now.year + 1):
        start = now.replace(year=year, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = start.replace(year=year + 1)
        yearly.append(
            {"label": str(year), "value": _dollars(_sum(qs.filter(created_at__gte=start, created_at__lt=end)))}
        )

    return {"weekly": weekly, "monthly": monthly, "yearly": yearly}


def return_queryset(user=None):
    qs = BalanceTransaction.objects.filter(type=BalanceTransaction.Type.RETURN, status=SUCCESS)
    if user is not None:
        qs = qs.filter(balance__user=user)
    return qs
