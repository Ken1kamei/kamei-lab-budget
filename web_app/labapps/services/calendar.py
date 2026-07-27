import logging
from datetime import datetime, time, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

import google.auth
from django.conf import settings
from django.core.cache import cache
from google.auth.transport.requests import AuthorizedSession


logger = logging.getLogger(__name__)
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


def _week_bounds(now=None):
    zone = ZoneInfo(settings.LAB_CALENDAR_TIME_ZONE)
    current = now.astimezone(zone) if now else datetime.now(zone)
    start_date = current.date() - timedelta(days=current.weekday())
    start = datetime.combine(start_date, time.min, tzinfo=zone)
    return start, start + timedelta(days=7), zone


def _parse_event_time(value, zone):
    if value.get("dateTime"):
        return datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00")).astimezone(zone)
    if value.get("date"):
        return datetime.combine(
            datetime.fromisoformat(value["date"]).date(), time.min, tzinfo=zone
        )
    return None


def _event_context(event, zone):
    start = _parse_event_time(event.get("start", {}), zone)
    end = _parse_event_time(event.get("end", {}), zone)
    all_day = bool(event.get("start", {}).get("date"))
    return {
        "id": str(event.get("id") or ""),
        "title": str(event.get("summary") or "Untitled event"),
        "start": start,
        "end": end,
        "all_day": all_day,
        "time_label": "All day" if all_day else (start.strftime("%H:%M") if start else ""),
        "location": str(event.get("location") or ""),
        "url": str(event.get("htmlLink") or ""),
    }


def _empty_week(start, status, message):
    return {
        "status": status,
        "message": message,
        "week_label": f"{start.strftime('%b %-d')} – {(start + timedelta(days=6)).strftime('%b %-d, %Y')}",
        "days": [
            {
                "date": (start + timedelta(days=offset)).date(),
                "label": (start + timedelta(days=offset)).strftime("%a"),
                "date_label": (start + timedelta(days=offset)).strftime("%-d %b"),
                "events": [],
            }
            for offset in range(7)
        ],
    }


def lab_calendar_week(now=None):
    start, end, zone = _week_bounds(now)
    if not settings.LAB_CALENDAR_ID:
        return _empty_week(start, "not_configured", "Lab calendar is not configured.")

    cache_key = f"lab-calendar-week:{settings.LAB_CALENDAR_ID}:{start.date().isoformat()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    result = _empty_week(start, "ready", "")
    try:
        credentials, _ = google.auth.default(scopes=[CALENDAR_SCOPE])
        response = AuthorizedSession(credentials).get(
            "https://www.googleapis.com/calendar/v3/calendars/"
            f"{quote(settings.LAB_CALENDAR_ID, safe='')}/events",
            params={
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "singleEvents": "true",
                "orderBy": "startTime",
                "maxResults": 100,
                "timeZone": settings.LAB_CALENDAR_TIME_ZONE,
            },
            timeout=5,
        )
        response.raise_for_status()
        for raw_event in response.json().get("items", []):
            event = _event_context(raw_event, zone)
            if not event["start"]:
                continue
            day_index = (event["start"].date() - start.date()).days
            if 0 <= day_index < 7:
                result["days"][day_index]["events"].append(event)
    except Exception as error:
        logger.warning("Lab Calendar unavailable: %s", error)
        result = _empty_week(
            start,
            "unavailable",
            "Calendar access is being configured. The rest of the Portal remains available.",
        )

    cache.set(cache_key, result, 300)
    return result
