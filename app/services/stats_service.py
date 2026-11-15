"""Aggregate click analytics for a short link."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.base import ensure_aware, utcnow
from app.models.click import Click
from app.models.link import Link

#: How many days of the daily histogram are returned.
HISTORY_DAYS = 30
#: How many top referers are returned.
TOP_SOURCES = 5
#: Label used when a click has no referer.
DIRECT_SOURCE = "direct"


def collect_stats(db: Session, link: Link) -> dict:
    """Build the analytics payload for one link."""
    link_id = int(link.id)
    filters = (Click.link_id == link_id,)

    total = int(db.scalar(select(func.count(Click.id)).where(*filters)) or 0)
    unique = int(db.scalar(select(func.count(distinct(Click.ip_hash))).where(*filters)) or 0)
    first_click = db.scalar(select(func.min(Click.clicked_at)).where(*filters))
    last_click = db.scalar(select(func.max(Click.clicked_at)).where(*filters))

    start_day = utcnow().date() - timedelta(days=HISTORY_DAYS - 1)
    window_start = datetime.combine(start_day, time.min, tzinfo=UTC)
    stamps = db.execute(
        select(Click.clicked_at).where(*filters, Click.clicked_at >= window_start)
    ).scalars()
    per_day: Counter[str] = Counter()
    for stamp in stamps:
        moment = ensure_aware(stamp)
        if moment is not None:
            per_day[moment.date().isoformat()] += 1

    days = [
        {
            "date": (start_day + timedelta(days=offset)).isoformat(),
            "clicks": per_day.get((start_day + timedelta(days=offset)).isoformat(), 0),
        }
        for offset in range(HISTORY_DAYS)
    ]

    source = func.coalesce(Click.referer, DIRECT_SOURCE)
    referer_rows = db.execute(
        select(source, func.count(Click.id))
        .where(*filters)
        .group_by(source)
        .order_by(func.count(Click.id).desc(), source.asc())
        .limit(TOP_SOURCES)
    ).all()
    referers = [{"source": str(row[0]), "clicks": int(row[1])} for row in referer_rows]

    device_rows = db.execute(
        select(Click.device_type, func.count(Click.id))
        .where(*filters)
        .group_by(Click.device_type)
        .order_by(func.count(Click.id).desc(), Click.device_type.asc())
    ).all()
    devices = [{"device": str(row[0]), "clicks": int(row[1])} for row in device_rows]

    return {
        "link_id": link_id,
        "code": str(link.code),
        "short_url": settings.short_url(str(link.code)),
        "original_url": str(link.original_url),
        "total_clicks": total,
        "unique_visitors": unique,
        "first_click_at": ensure_aware(first_click),
        "last_click_at": ensure_aware(last_click),
        "created_at": ensure_aware(link.created_at),
        "expires_at": ensure_aware(link.expires_at),
        "days": days,
        "referers": referers,
        "devices": devices,
    }
