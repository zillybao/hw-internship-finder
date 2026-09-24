"""Page-only catalog for graduate roles that are not written to the sheet."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from src.dedupe import normalize_link
from src.filter import filter_by_description, matched_keywords
from src.models import JobPosting

_CATALOG_KEYS = (
    "company",
    "title",
    "link",
    "date_posted",
    "date_found",
    "keywords",
    "source_page",
)


class PublicExtraCatalog:
    """Graduate listings for the public page. Never written to the sheet."""

    def __init__(self, path: Path, listings: list[dict[str, object]] | None = None) -> None:
        self.path = path
        self.listings: list[dict[str, object]] = list(listings or [])

    @classmethod
    def load(cls, path: Path) -> PublicExtraCatalog:
        if not path.exists():
            return cls(path)
        raw = json.loads(path.read_text(encoding="utf-8")) or {}
        listings = raw.get("listings") if isinstance(raw, dict) else None
        if not isinstance(listings, list):
            listings = []
        return cls(path, [item for item in listings if isinstance(item, dict)])

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"listings": self.listings}
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def drop_absent(self, source_page: str, live_links: set[str]) -> int:
        """Drop this source's entries whose links are gone from a successful scan."""
        live_norm = {normalize_link(link) for link in live_links if link}
        kept: list[dict[str, object]] = []
        removed = 0
        for entry in self.listings:
            if str(entry.get("source_page") or "") != source_page:
                kept.append(entry)
                continue
            if normalize_link(str(entry.get("link") or "")) in live_norm:
                kept.append(entry)
                continue
            removed += 1
        self.listings = kept
        return removed

    def drop_links(self, source_page: str, links: set[str]) -> int:
        """Drop this source's entries for the given links (keyword misses)."""
        banned = {normalize_link(link) for link in links if link}
        if not banned:
            return 0
        kept: list[dict[str, object]] = []
        removed = 0
        for entry in self.listings:
            same_source = str(entry.get("source_page") or "") == source_page
            if same_source and normalize_link(str(entry.get("link") or "")) in banned:
                removed += 1
                continue
            kept.append(entry)
        self.listings = kept
        return removed

    def upsert(self, postings: list[JobPosting], *, today: date) -> int:
        """Insert or refresh page-only rows. Existing date_found is kept."""
        by_link = {
            normalize_link(str(entry.get("link") or "")): entry for entry in self.listings
        }
        added = 0
        for posting in postings:
            if not posting.matched_keywords or not posting.link:
                continue
            key = normalize_link(posting.link)
            previous = by_link.get(key)
            date_found = (
                str(previous.get("date_found") or "")
                if previous
                else today.isoformat()
            )
            record = {
                "company": posting.company,
                "title": posting.title,
                "link": posting.link,
                "date_posted": posting.date_posted.isoformat() if posting.date_posted else "",
                "date_found": date_found or today.isoformat(),
                "keywords": list(posting.matched_keywords),
                "source_page": posting.source_page,
            }
            if set(record) != set(_CATALOG_KEYS):
                raise ValueError("graduate catalog record escaped its field list")
            if previous is None:
                self.listings.append(record)
                by_link[key] = record
                added += 1
            else:
                previous.update(record)
        return added


def sync_graduate_catalog(
    catalog: PublicExtraCatalog,
    *,
    source_page: str,
    live_links: set[str],
    grad_only: list[JobPosting],
    keywords: list[str],
    aliases: dict[str, str] | None,
    today: date,
) -> tuple[list[JobPosting], list[JobPosting]]:
    """Refresh one company's page-only graduate rows after a successful parse.

    Keyword hits are upserted. Keyword misses and links missing from
    ``live_links`` are removed. Descriptions are cleared and are not stored.
    """
    kept, missed = filter_by_description(grad_only, keywords, aliases=aliases)
    for posting in kept:
        posting.matched_keywords = matched_keywords(
            posting.description,
            keywords,
            aliases,
        )
        posting.description = ""
    catalog.drop_absent(source_page, live_links)
    catalog.drop_links(source_page, {posting.link for posting in missed})
    catalog.upsert(kept, today=today)
    return kept, missed
