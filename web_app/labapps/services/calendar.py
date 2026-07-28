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
SOURCE_COLOR_COUNT = 7


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


def _calendar_sources():
    sources = []
    if settings.LAB_CALENDAR_ID:
        sources.append(
            {"id": settings.LAB_CALENDAR_ID, "label": "Lab calendar"}
        )
    for raw_source in settings.LAB_CALENDAR_SOURCES.split(";"):
        raw_source = raw_source.strip()
        if not raw_source:
            continue
        label, separator, calendar_id = raw_source.partition("|")
        if not separator or not label.strip() or not calendar_id.strip():
            logger.warning("Ignoring invalid LAB_CALENDAR_SOURCES entry: %s", raw_source)
            continue
        sources.append({"id": calendar_id.strip(), "label": label.strip()})

    deduplicated = []
    seen_ids = set()
    for source in sources:
        if source["id"] in seen_ids:
            continue
        source = {**source, "color_index": len(deduplicated) % SOURCE_COLOR_COUNT}
        deduplicated.append(source)
        seen_ids.add(source["id"])
    return deduplicated


def _event_context(event, zone, source):
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
        "calendar_label": source["label"],
        "calendar_color_index": source["color_index"],
    }


def _empty_week(start, status, message):
    return {
        "status": status,
        "message": message,
        "sources": [],
        "unavailable_sources": [],
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
    sources = _calendar_sources()
    if not sources:
        return _empty_week(start, "not_configured", "Lab calendar is not configured.")

    source_key = ":".join(source["id"] for source in sources)
    cache_key = f"lab-calendar-week:{source_key}:{start.date().isoformat()}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    result = _empty_week(start, "ready", "")
    try:
        credentials, _ = google.auth.default(scopes=[CALENDAR_SCOPE])
        session = AuthorizedSession(credentials)
        for source in sources:
            try:
                response = session.get(
                    "https://www.googleapis.com/calendar/v3/calendars/"
                    f"{quote(source['id'], safe='')}/events",
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
                source_context = {**source, "event_count": 0}
                for raw_event in response.json().get("items", []):
                    event = _event_context(raw_event, zone, source)
                    if not event["start"]:
                        continue
                    day_index = (event["start"].date() - start.date()).days
                    if 0 <= day_index < 7:
                        result["days"][day_index]["events"].append(event)
                        source_context["event_count"] += 1
                result["sources"].append(source_context)
            except Exception as error:
                logger.warning("Calendar %s unavailable: %s", source["label"], error)
                result["unavailable_sources"].append(source["label"])

        for day in result["days"]:
            day["events"].sort(
                key=lambda event: (event["start"], event["calendar_label"], event["title"])
            )
        if not result["sources"]:
            raise RuntimeError("No configured calendars were available.")
        if result["unavailable_sources"]:
            result["message"] = "Some shared calendars are temporarily unavailable."
    except Exception as error:
        logger.warning("Lab Calendar unavailable: %s", error)
        result = _empty_week(
            start,
            "unavailable",
            "Calendar access is being configured. The rest of the Portal remains available.",
        )

    cache.set(cache_key, result, 300)
    return result
