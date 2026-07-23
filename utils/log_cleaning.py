""" ANSI Stripping , time stripping ,validate input is empty , reject input if its too short(<5)"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_TIMESTAMP_RE = re.compile(r"^\[?\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(\.\d+)?Z?\]?\s*")
_MULTI_BLANK_RE = re.compile(r"\n\s*\n+")

MAX_LOG_CHARS = 4000
MIN_LOG_CHARS = 5


class LogValidationError(ValueError):
    """Raised when input log text fails basic validation.

    Callers (API layer) catch this and return the structured error response
    described in the capstone's Error Handling Strategy, rather than letting
    an unhandled exception propagate.
    """


def clean_log_text(raw_text: str) -> str:
    text = _ANSI_RE.sub("", raw_text)
    lines = [
        _TIMESTAMP_RE.sub("", line).rstrip()
        for line in text.splitlines()
    ]
    text = "\n".join(lines)
    text = _MULTI_BLANK_RE.sub("\n", text).strip()
    if len(text) > MAX_LOG_CHARS:
        text = text[:MAX_LOG_CHARS] + "\n...[truncated]"
    return text


def validate_log_input(raw_text: str | None) -> str:
    """Validate + clean raw log input. Raises LogValidationError on failure.

    Covers:
      - Empty Input -> prompt user validation
      - unsupported data -> graceful rejection
    """
    if raw_text is None or not raw_text.strip():
        raise LogValidationError("Log input is empty. Please paste a Jenkins console log or failure snippet.")

    cleaned = clean_log_text(raw_text)

    if len(cleaned) < MIN_LOG_CHARS:
        raise LogValidationError("Log input is too short to analyze meaningfully.")

    # Reject obviously non-log/binary input (unsupported data)
    printable_ratio = sum(1 for c in cleaned if c.isprintable() or c in "\n\t") / max(len(cleaned), 1)
    if printable_ratio < 0.85:
        raise LogValidationError("Input does not look like a valid text log (too many non-printable characters).")

    return cleaned


if __name__ == "__main__":
    sample = "\x1b[31m[2026-06-01 10:22:31] ERROR Build failed\x1b[0m\n\n\nExit code 137"
    print(repr(clean_log_text(sample)))
