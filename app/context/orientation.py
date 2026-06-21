"""Session orientation: the date, time, and place an agent needs to ground itself.

Agent harnesses routinely lack a reliable sense of *now* and *where* — they guess
the date, ignore the operator's timezone, and have no notion of location. Sia is
the default first stop for context, so it states these plainly at the top of every
artifact. The operator configures a timezone and (optionally) a location; the date
and time are computed live at build time.

Location is personal, so the builder only populates it for principals trusted with
private visibility — date, time, and timezone are shown to everyone.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "UTC"


def resolve_timezone(name: str) -> tuple[tzinfo, str]:
    """Resolve an IANA tz name to a tzinfo, falling back to UTC when the name is
    unknown or the system tz database is unavailable (e.g. a slim container with
    no tzdata). Returns (tzinfo, canonical_name)."""
    candidate = (name or "").strip()
    if not candidate or candidate.upper() == "UTC":
        return timezone.utc, "UTC"
    try:
        return ZoneInfo(candidate), candidate
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown owner_timezone %r; falling back to UTC", name)
        return timezone.utc, "UTC"


@dataclass(frozen=True)
class Orientation:
    now: datetime  # tz-aware, already in the resolved zone
    timezone_name: str
    location: str | None = None

    @property
    def date(self) -> str:
        return self.now.strftime("%Y-%m-%d")

    @property
    def day_of_week(self) -> str:
        return self.now.strftime("%A")

    @property
    def time(self) -> str:
        return self.now.strftime("%H:%M")

    @property
    def utc_offset(self) -> str:
        # %z gives e.g. "-0700"; render as "-07:00" (and "+00:00" for UTC).
        offset = self.now.strftime("%z")
        return f"{offset[:3]}:{offset[3:]}" if offset else "+00:00"

    @property
    def tz_abbrev(self) -> str:
        return self.now.strftime("%Z") or self.timezone_name

    def to_dict(self) -> dict:
        data = {
            "date": self.date,
            "day_of_week": self.day_of_week,
            "time": self.time,
            "datetime": self.now.isoformat(timespec="seconds"),
            "timezone": self.timezone_name,
            "utc_offset": self.utc_offset,
        }
        if self.location:
            data["location"] = self.location
        return data

    def to_markdown(self) -> str:
        # Day without a leading zero ("15" not "05") without relying on the
        # non-portable %-d directive.
        long_date = f"{self.day_of_week}, {self.now.day} {self.now.strftime('%B %Y')}"
        lines = [
            "## Session orientation",
            "",
            f"- **Date:** {long_date} ({self.date})",
            f"- **Time:** {self.time} {self.tz_abbrev} (UTC{self.utc_offset})",
            f"- **Timezone:** {self.timezone_name}",
        ]
        if self.location:
            lines.append(f"- **Location:** {self.location}")
        return "\n".join(lines)


def build_orientation(
    timezone_name: str,
    location: str | None = None,
    *,
    include_location: bool = True,
    now: datetime | None = None,
) -> Orientation:
    """Compute the current orientation. ``now`` (any tz-aware instant) is for
    deterministic tests; production passes nothing and uses the wall clock."""
    tz, resolved_name = resolve_timezone(timezone_name)
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    moment = base.astimezone(tz)
    place = location.strip() if location and location.strip() else None
    return Orientation(
        now=moment,
        timezone_name=resolved_name,
        location=place if include_location else None,
    )
