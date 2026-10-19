"""Shared UTC serialization; database datetime values are stored in UTC."""
import datetime


def iso_utc(value: datetime.datetime | None) -> str | None:
    if value is None:
        return None
    text = value.replace(tzinfo=datetime.timezone.utc).isoformat(timespec="seconds")
    return text.replace("+00:00", "Z")
