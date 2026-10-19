"""Shared UTC serialization; database datetime values are stored in UTC."""
import datetime


def utc_now() -> datetime.datetime:
    """Return naive UTC, matching the database's UTC DATETIME convention."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def iso_utc(value: datetime.datetime | None) -> str | None:
    if value is None:
        return None
    text = value.replace(tzinfo=datetime.timezone.utc).isoformat(timespec="seconds")
    return text.replace("+00:00", "Z")
