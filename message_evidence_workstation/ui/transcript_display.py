"""Transcript display formatting and speaker tint defaults."""

from __future__ import annotations

from datetime import datetime

DEFAULT_SPEAKER_TINTS: list[str] = [
    "#f3eee6",
    "#e9eef2",
    "#eaefe8",
    "#f0e9ee",
    "#e7efe9",
    "#ece8f0",
    "#f0ece3",
    "#e8eaf0",
]


def normalize_speaker_tints(colors: list[str] | None) -> list[str]:
    tints = list(colors or [])
    while len(tints) < 8:
        tints.append(DEFAULT_SPEAKER_TINTS[len(tints)])
    return tints[:8]


def build_sender_participant_map(messages: list) -> dict[str, int]:
    sender_keys = sorted(
        {
            (message.sender_id or message.sender_display or "").strip()
            for message in messages
            if (message.sender_id or message.sender_display or "").strip()
        }
    )
    return {sender_key: index % 8 for index, sender_key in enumerate(sender_keys)}


def _timezone_abbrev(dt: datetime) -> str:
    label = dt.tzname()
    if label:
        return label
    offset = dt.utcoffset()
    if offset is None:
        return "UTC"
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    hours, minutes = divmod(total_minutes, 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def format_timestamp_label(timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return timestamp
    hour = dt.strftime("%I").lstrip("0") or "12"
    minute = dt.strftime("%M")
    ampm = dt.strftime("%p")
    date_part = f"{dt.strftime('%B')} {dt.day}, {dt.year}"
    time_part = f"{hour}:{minute}{ampm}"
    tz_part = _timezone_abbrev(dt)
    return f"{date_part} : {time_part} {tz_part}"
