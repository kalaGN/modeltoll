"""Request deduplication digests; never persist keys or request bodies."""
import hashlib
import json
from typing import Any


class InvalidIdempotencyKey(ValueError):
    """Header must contain 1–128 visible ASCII characters without whitespace."""


def prepare(key: str | None, endpoint: str, model: str,
            body: dict[str, Any]) -> tuple[str, str] | None:
    if key is None:
        return None
    if not isinstance(key, str) or not 1 <= len(key) <= 128 or any(
            not 33 <= ord(char) <= 126 for char in key):
        raise InvalidIdempotencyKey('invalid idempotency key')
    encoded = json.dumps({'endpoint': endpoint, 'model': model, 'body': body},
                         sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                         allow_nan=False).encode('utf-8')
    return hashlib.sha256(key.encode('ascii')).hexdigest(), hashlib.sha256(encoded).hexdigest()
