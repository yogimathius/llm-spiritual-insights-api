"""Small HTTP input helpers shared by the JSON API views."""

from __future__ import annotations

import json
from typing import Any


def load_json_object(body: bytes) -> dict[str, Any]:
    """Decode a JSON request body and reject valid JSON with the wrong shape."""
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("JSON request body must be an object.")
    return data
