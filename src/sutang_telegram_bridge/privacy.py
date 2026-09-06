from __future__ import annotations

import re


REDACTED = "[REDACTED ACCESS MATERIAL]"

ACCESS_PATTERNS = (
    re.compile(r"\b[0-9]{6,12}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b", re.I),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b", re.I),
    re.compile(r"\b(?:xox[baprs]-)[A-Za-z0-9-]{16,}\b", re.I),
    re.compile(
        r"(?i)(\b(?:authorization|api[_ -]?key|access[_ -]?token|"
        r"refresh[_ -]?token|client[_ -]?secret|password|credential)\b"
        r"\s*(?::|=)\s*)(?:bearer\s+)?[^\s,;]{8,}"
    ),
    re.compile(r"(?i)(https?://[^\s/:@]+:)[^\s/@]+(@)"),
    re.compile(
        r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----.*?"
        r"-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----",
        re.S,
    ),
)


def redact_access_material(text: str) -> str:
    cleaned = str(text)
    for index, pattern in enumerate(ACCESS_PATTERNS):
        if index == 4:
            cleaned = pattern.sub(rf"\1{REDACTED}", cleaned)
        elif index == 5:
            cleaned = pattern.sub(rf"\1{REDACTED}\2", cleaned)
        else:
            cleaned = pattern.sub(REDACTED, cleaned)
    return cleaned
