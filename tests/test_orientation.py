"""Session-orientation tests: timezone resolution, rendering, visibility gating,
and that every build carries an orientation block."""

from datetime import datetime, timezone

from app.context.builder import ContextBuilder
from app.context.orientation import build_orientation, resolve_timezone
from app.context.principals import Principal
from tests.test_builder import OWNER, VISITOR, seed

# A fixed instant so date/time assertions are deterministic.
NOON_UTC = datetime(2026, 6, 15, 19, 30, tzinfo=timezone.utc)


def test_resolve_known_zone():
    tz, name = resolve_timezone("America/Los_Angeles")
    assert name == "America/Los_Angeles"
    assert NOON_UTC.astimezone(tz).strftime("%H:%M") == "12:30"


def test_resolve_unknown_zone_falls_back_to_utc():
    tz, name = resolve_timezone("Mars/Olympus_Mons")
    assert name == "UTC"
    assert NOON_UTC.astimezone(tz).utcoffset().total_seconds() == 0


def test_resolve_blank_is_utc():
    assert resolve_timezone("")[1] == "UTC"
    assert resolve_timezone("utc")[1] == "UTC"


def test_orientation_fields_and_offset():
    o = build_orientation("America/Los_Angeles", "San Francisco, CA", now=NOON_UTC)
    assert o.date == "2026-06-15"
    assert o.day_of_week == "Monday"
    assert o.time == "12:30"  # 19:30 UTC -> 12:30 PDT
    assert o.utc_offset == "-07:00"
    assert o.location == "San Francisco, CA"
    data = o.to_dict()
    assert data["timezone"] == "America/Los_Angeles"
    assert data["location"] == "San Francisco, CA"
    md = o.to_markdown()
    assert "Session orientation" in md
    assert "Monday, 15 June 2026 (2026-06-15)" in md
    assert "San Francisco, CA" in md


def test_location_excluded_when_not_permitted():
    o = build_orientation(
        "UTC", "Secret Lair", include_location=False, now=NOON_UTC
    )
    assert o.location is None
    assert "location" not in o.to_dict()
    assert "Location" not in o.to_markdown()


def test_blank_location_is_omitted():
    o = build_orientation("UTC", "   ", now=NOON_UTC)
    assert o.location is None


def test_naive_now_is_treated_as_utc():
    o = build_orientation("UTC", None, now=datetime(2026, 6, 15, 19, 30))
    assert o.time == "19:30"


async def test_owner_build_includes_orientation_with_location(db_session, store):
    embedder = await seed(db_session, store)
    builder = ContextBuilder(
        db_session, store, embedder,
        owner_timezone="America/Los_Angeles", owner_location="San Francisco, CA",
    )
    artifact = await builder.build("reciprocal rank fusion rankings", OWNER)
    assert artifact.orientation is not None
    assert artifact.orientation.location == "San Francisco, CA"
    markdown = artifact.to_markdown()
    assert "## Session orientation" in markdown
    assert "America/Los_Angeles" in markdown
    assert "San Francisco, CA" in markdown
    assert artifact.to_dict()["orientation"]["timezone"] == "America/Los_Angeles"


async def test_visitor_build_omits_location_but_keeps_datetime(db_session, store):
    embedder = await seed(db_session, store)
    builder = ContextBuilder(
        db_session, store, embedder,
        owner_timezone="America/Los_Angeles", owner_location="San Francisco, CA",
    )
    artifact = await builder.build("reciprocal rank fusion rankings", VISITOR)
    assert artifact.orientation is not None
    assert artifact.orientation.location is None
    markdown = artifact.to_markdown()
    assert "## Session orientation" in markdown
    assert "San Francisco, CA" not in markdown


async def test_builder_defaults_orientation_from_settings(db_session, store):
    embedder = await seed(db_session, store)
    # No tz/location passed -> falls back to settings (UTC by default).
    builder = ContextBuilder(db_session, store, embedder)
    tz_agent = Principal(
        id="agent-tz", kind="agent", token_budget=4000,
        allowed_visibilities=("public",), allow_fallback=False,
    )
    artifact = await builder.build("reciprocal rank fusion", tz_agent)
    assert artifact.orientation is not None
    assert artifact.orientation.timezone_name == "UTC"
