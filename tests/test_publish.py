"""Public page payload: allowlist, closed rows, and retention."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.publish import (
    assert_public_payload,
    build_public_payload,
    load_retain_days,
    render_listings_js,
    select_public_listings,
    write_site,
)

TODAY = date(2026, 9, 24)
RETAIN = 14


def _row(**overrides: str) -> dict[str, str]:
    base = {
        "company": "Acme",
        "title": "Firmware Intern",
        "link": "https://example.com/jobs/1",
        "location": "Austin, TX",
        "status": "open",
        "date_found": "2026-09-22",
        "date_posted": "2026-09-20",
        "source_page": "https://example.com/careers",
        "matched_keywords": "firmware, embedded",
        "description": "secret body text",
    }
    base.update(overrides)
    return base


def test_select_public_listings_drops_closed_expired_and_unknown_keywords() -> None:
    rows = [
        _row(),
        _row(
            company="Closed Co",
            link="https://example.com/jobs/closed",
            status="closed",
        ),
        _row(
            company="Old Co",
            link="https://example.com/jobs/old",
            date_posted="2026-09-09",
            date_found="2026-09-22",
        ),
        _row(
            company="Legacy Co",
            link="https://example.com/jobs/legacy",
            matched_keywords="",
        ),
        _row(
            company="Applied Co",
            title="FPGA Intern",
            link="https://example.com/jobs/applied",
            status="applied",
            date_posted="2026-09-18",
            matched_keywords="fpga",
        ),
        _row(
            company="Undated Co",
            link="https://example.com/jobs/undated",
            date_posted="",
            date_found="2026-09-20",
            matched_keywords="rtl",
        ),
        _row(
            company="Stale Undated",
            link="https://example.com/jobs/stale",
            date_posted="",
            date_found="2026-09-01",
            matched_keywords="mcu",
        ),
    ]
    listings = select_public_listings(rows, today=TODAY, retain_days=RETAIN)
    by_company = {item["company"]: item for item in listings}
    assert set(by_company) == {"Acme", "Applied Co", "Undated Co"}
    assert by_company["Applied Co"]["keywords"] == ["fpga"]
    assert "status" not in by_company["Applied Co"]
    assert by_company["Undated Co"]["date_posted"] == ""
    assert listings[0]["date_posted"] >= listings[-1]["date_posted"]


def test_boundary_day_is_kept() -> None:
    rows = [
        _row(date_posted="2026-09-10", date_found="2026-09-10"),
        _row(
            company="Too Old",
            link="https://example.com/jobs/too-old",
            date_posted="2026-09-09",
        ),
    ]
    listings = select_public_listings(rows, today=TODAY, retain_days=RETAIN)
    assert [item["company"] for item in listings] == ["Acme"]


def test_payload_allowlist_omits_private_fields() -> None:
    payload = build_public_payload(
        [_row()],
        today=TODAY,
        retain_days=RETAIN,
        updated=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )
    assert set(payload) == {"updated", "listings"}
    listing = payload["listings"][0]
    assert set(listing) == {"company", "title", "link", "date_posted", "keywords"}
    assert listing["keywords"] == ["firmware", "embedded"]
    blob = render_listings_js(payload)
    assert "applied" not in blob
    assert "Austin" not in blob
    assert "secret body" not in blob
    assert "source_page" not in blob
    assert "example.com/careers" not in blob


def test_assert_public_payload_rejects_status() -> None:
    payload = {
        "updated": "2026-09-24T00:00:00Z",
        "listings": [
            {
                "company": "Acme",
                "title": "Intern",
                "link": "https://example.com/1",
                "date_posted": "2026-09-20",
                "keywords": ["fpga"],
                "status": "applied",
            }
        ],
    }
    with pytest.raises(ValueError, match="allowlist"):
        assert_public_payload(payload)


def test_render_listings_js_escapes_markup() -> None:
    payload = build_public_payload(
        [_row(title="Firmware <script> Intern")],
        today=TODAY,
        retain_days=RETAIN,
        updated=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )
    blob = render_listings_js(payload)
    assert "<script>" not in blob
    assert "\\u003cscript\\u003e" in blob


def test_write_site_copies_page(tmp_path: Path) -> None:
    site = tmp_path / "site"
    dist = tmp_path / "dist"
    site.mkdir()
    (site / "index.html").write_text("<p>board</p>", encoding="utf-8")
    payload = build_public_payload(
        [_row()],
        today=TODAY,
        retain_days=RETAIN,
        updated=datetime(2026, 9, 24, tzinfo=timezone.utc),
    )
    write_site(payload, site_dir=site, dist_dir=dist)
    assert (dist / "index.html").read_text(encoding="utf-8") == "<p>board</p>"
    assert "window.LISTINGS" in (dist / "listings.js").read_text(encoding="utf-8")


def test_payload_merges_graduate_catalog_and_drops_expired() -> None:
    extra = [
        {
            "company": "Grad Co",
            "title": "FPGA Intern",
            "link": "https://example.com/jobs/grad",
            "date_posted": "2026-09-20",
            "date_found": "2026-09-22",
            "keywords": ["fpga"],
            "source_page": "https://example.com/careers",
            "description": "must not leak",
        },
        {
            "company": "Old Grad",
            "title": "ASIC Intern",
            "link": "https://example.com/jobs/old-grad",
            "date_posted": "2026-09-01",
            "date_found": "2026-09-02",
            "keywords": ["asic"],
            "source_page": "https://example.com/careers",
        },
        {
            "company": "Sheet Wins",
            "title": "From the sheet",
            "link": "https://example.com/jobs/1",
            "date_posted": "2026-09-19",
            "date_found": "2026-09-22",
            "keywords": ["firmware"],
            "source_page": "https://example.com/careers",
        },
    ]
    payload = build_public_payload(
        [_row()],
        today=TODAY,
        retain_days=RETAIN,
        updated=datetime(2026, 9, 24, tzinfo=timezone.utc),
        extra_entries=extra,
    )
    by_link = {item["link"]: item for item in payload["listings"]}
    assert set(by_link) == {
        "https://example.com/jobs/1",
        "https://example.com/jobs/grad",
    }
    assert by_link["https://example.com/jobs/1"]["title"] == "Firmware Intern"
    grad = by_link["https://example.com/jobs/grad"]
    assert set(grad) == {"company", "title", "link", "date_posted", "keywords"}
    blob = render_listings_js(payload)
    assert "source_page" not in blob
    assert "must not leak" not in blob
    assert "Old Grad" not in blob


def test_load_retain_days_default() -> None:
    assert load_retain_days(Path(__file__).resolve().parent.parent / "config" / "public.yaml") == 14
