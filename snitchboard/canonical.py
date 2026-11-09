"""Canonical JSON and SHA-256 digests (HSB-PRD-001 section 7.3).

Canonical form: keys sorted, no insignificant whitespace, UTF-8 without
escaping non-ASCII characters. NaN and infinity are refused because they have
no JSON representation and would make a digest depend on the serialiser.
"""

import hashlib
import json


def canonical_bytes(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_of(value):
    """Hex SHA-256 of the canonical JSON encoding of `value`."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()
