"""Bounded JSON lines shared by the local daemon and its client."""

import json


MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate field")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Non-finite number")


def encode_frame(value: dict[str, object], limit: int) -> bytes:
    raw = (json.dumps(value, ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
    if len(raw) > limit:
        raise ValueError("Frame too large")
    return raw


def decode_frame(raw: bytes, limit: int) -> dict[str, object]:
    if len(raw) > limit or not raw.endswith(b"\n"):
        raise ValueError("Invalid frame")
    value = json.loads(
        raw.decode("utf-8"), object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("Invalid object")
    return value
