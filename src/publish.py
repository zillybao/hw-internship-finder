"""Build the public listings page from the private sheet.

The page payload is an allowlist: company, title, link, date_posted, keywords.
Status, location, description, source page, and credentials never leave this module.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from src.sheet import JobSheet, SheetError

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "public.yaml"
SITE_DIR = ROOT / "site"
DIST_DIR = ROOT / "dist"

PUBLIC_LISTING_KEYS = ("company", "title", "link", "date_posted", "keywords")
PUBLIC_PAYLOAD_KEYS = ("updated", "listings")
_DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%b %d, %Y", "%B %d, %Y")


def load_retain_days(path: Path = CONFIG_PATH) -> int:
    """Days a listing stays on the public page. Defaults to 14."""
    if not path.exists():
        return 14
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or "retain_days" not in data:
        return 14
    days = int(data["retain_days"])
    if days < 0:
        raise ValueError("retain_days must be >= 0")
    return days


def parse_sheet_date(value: str) -> date | None:
    """Parse an ISO or common spreadsheet date. Unknown text is not a date."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_keyword_cell(value: str) -> list[str]:
    """Split a comma-separated keyword cell. Empty pieces are dropped."""
    found: list[str] = []
    for part in (value or "").split(","):
        keyword = part.strip().lower()
        if keyword and keyword not in found:
            found.append(keyword)
    return found


def listing_age_anchor(row: dict[str, str]) -> date | None:
    """date_posted when it parses; otherwise date_found."""
    posted = parse_sheet_date(str(row.get("date_posted") or ""))
    if posted is not None:
        return posted
    return parse_sheet_date(str(row.get("date_found") or ""))


def select_public_listings(
    rows: list[dict[str, str]],
    *,
    today: date,
    retain_days: int,
) -> list[dict[str, Any]]:
    """Rows that belong on the public page, newest posted date first.

    Closed rows, rows with no stored keywords, and rows older than
    ``retain_days`` are omitted. ``applied`` is kept without a status field.
    """
    selected: list[dict[str, Any]] = []
    for row in rows:
        status = str(row.get("status") or "").strip().lower()
        if status == "closed":
            continue
        keywords = parse_keyword_cell(str(row.get("matched_keywords") or ""))
        if not keywords:
            continue
        anchor = listing_age_anchor(row)
        if anchor is None or (today - anchor).days > retain_days:
            continue
        company = str(row.get("company") or "").strip()
        title = str(row.get("title") or "").strip()
        link = str(row.get("link") or "").strip()
        if not company or not title or not link:
            continue
        selected.append(
            {
                "company": company,
                "title": title,
                "link": link,
                "date_posted": str(row.get("date_posted") or "").strip(),
                "keywords": keywords,
            }
        )
    selected.sort(key=lambda item: item["date_posted"] or "", reverse=True)
    return selected


def build_public_payload(
    rows: list[dict[str, str]],
    *,
    today: date,
    retain_days: int,
    updated: datetime | None = None,
) -> dict[str, Any]:
    """Allowlisted page payload. Raises if a listing picks up any other key."""
    moment = updated or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    stamp = moment.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    stamp = stamp.replace("+00:00", "Z")
    payload = {
        "updated": stamp,
        "listings": select_public_listings(rows, today=today, retain_days=retain_days),
    }
    assert_public_payload(payload)
    return payload


def assert_public_payload(payload: dict[str, Any]) -> None:
    """Reject anything outside the public allowlist."""
    if set(payload) != set(PUBLIC_PAYLOAD_KEYS):
        extra = sorted(set(payload) - set(PUBLIC_PAYLOAD_KEYS))
        missing = sorted(set(PUBLIC_PAYLOAD_KEYS) - set(payload))
        raise ValueError(f"public payload keys mismatch extra={extra} missing={missing}")
    listings = payload["listings"]
    if not isinstance(listings, list):
        raise ValueError("public payload listings must be a list")
    for item in listings:
        if not isinstance(item, dict) or set(item) != set(PUBLIC_LISTING_KEYS):
            raise ValueError("public listing escaped the allowlist")
        if not isinstance(item["keywords"], list):
            raise ValueError("public listing keywords must be a list")


def render_listings_js(payload: dict[str, Any]) -> str:
    """JSON assignment safe to load from a static script tag."""
    assert_public_payload(payload)
    blob = json.dumps(payload, ensure_ascii=True, indent=2)
    blob = blob.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f"window.LISTINGS = {blob};\n"


def write_site(
    payload: dict[str, Any],
    *,
    site_dir: Path = SITE_DIR,
    dist_dir: Path = DIST_DIR,
) -> None:
    """Copy the static page and write generated listings into ``dist_dir``."""
    dist_dir.mkdir(parents=True, exist_ok=True)
    html = (site_dir / "index.html").read_text(encoding="utf-8")
    (dist_dir / "index.html").write_text(html, encoding="utf-8")
    (dist_dir / "listings.js").write_text(render_listings_js(payload), encoding="utf-8")


def publish_from_sheet(
    *,
    today: date | None = None,
    retain_days: int | None = None,
    dist_dir: Path = DIST_DIR,
    public_config: Path = CONFIG_PATH,
) -> dict[str, Any]:
    """Read the private sheet and write the public site. Does not deploy."""
    sheet = JobSheet(read_only=True)
    rows = sheet.all_rows()
    payload = build_public_payload(
        rows,
        today=today or date.today(),
        retain_days=load_retain_days(public_config) if retain_days is None else retain_days,
    )
    write_site(payload, dist_dir=dist_dir)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write the public listings page from the private Google Sheet.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DIST_DIR,
        help="Directory for index.html and listings.js (default: dist/).",
    )
    parser.add_argument(
        "--public-config",
        type=Path,
        default=CONFIG_PATH,
        help="Path to public.yaml",
    )
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env")
    try:
        payload = publish_from_sheet(dist_dir=args.out, public_config=args.public_config)
    except SheetError:
        print(
            "Sheet unavailable. Check the service-account secret and GOOGLE_SHEET_ID.",
            file=sys.stderr,
        )
        return 2
    print(f"Wrote {len(payload['listings'])} listing(s) to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
