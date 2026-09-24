"""Tests for spreadsheet helpers that do not need the Sheets API."""

from src.dedupe import identity_hashes
from src.models import SHEET_HEADERS, JobPosting
from src.sheet import (
    needs_date_posted_column,
    needs_matched_keywords_column,
    records_from_values,
    resolve_seen_worksheet_name,
    resolve_worksheet_name,
    seen_links_needing_backfill,
    spreadsheet_id_from_value,
)


def test_spreadsheet_id_from_raw_id() -> None:
    assert spreadsheet_id_from_value(" your-spreadsheet-id ") == "your-spreadsheet-id"


def test_spreadsheet_id_from_docs_url() -> None:
    url = (
        "https://docs.google.com/spreadsheets/d/"
        "your-spreadsheet-id/edit?gid=0#gid=0"
    )
    assert spreadsheet_id_from_value(url) == "your-spreadsheet-id"


def test_records_from_values_ignores_z1_schema_sentinel() -> None:
    header = list(SHEET_HEADERS) + [""] * 16 + ["schema_version=2"]
    values = [
        header,
        ["Acme", "Firmware Intern", "https://example.com/1", "Austin", "open", "2026-08-18", "", "https://board"],
        ["", "", "", "", "", "", "", ""],
    ]
    rows = records_from_values(values)
    assert len(rows) == 1
    assert rows[0]["company"] == "Acme"
    assert rows[0]["link"] == "https://example.com/1"
    assert rows[0]["source_page"] == "https://board"
    assert "schema_version=2" not in rows[0].values()


def test_records_from_values_reads_matched_keywords_column() -> None:
    values = [
        list(SHEET_HEADERS),
        [
            "Acme",
            "Firmware Intern",
            "https://example.com/1",
            "Austin",
            "open",
            "2026-08-18",
            "2026-09-20",
            "https://board",
            "firmware, embedded",
        ],
    ]
    rows = records_from_values(values)
    assert rows[0]["matched_keywords"] == "firmware, embedded"
    assert rows[0]["source_page"] == "https://board"


def test_matched_keywords_column_appends_without_shifting() -> None:
    v1 = [
        "company",
        "title",
        "link",
        "location",
        "status",
        "date_found",
        "date_posted",
        "source_page",
    ]
    assert needs_matched_keywords_column(v1) is True
    assert needs_date_posted_column(v1) is False
    assert v1 == SHEET_HEADERS[:8]
    assert SHEET_HEADERS[8] == "matched_keywords"
    assert needs_matched_keywords_column(list(SHEET_HEADERS)) is False


def test_sheet_row_appends_matched_keywords() -> None:
    posting = JobPosting(
        company="Acme",
        title="Firmware Intern",
        link="https://example.com/1",
        source_page="https://board",
        matched_keywords=["firmware", "embedded"],
    )
    row = posting.sheet_row()
    assert len(row) == len(SHEET_HEADERS)
    assert row[7] == "https://board"
    assert row[8] == "firmware, embedded"


def test_records_from_values_uses_positional_headers_when_renamed() -> None:
    values = [
        ["Company", "Title", "Job URL", "Where", "Status", "Found", "Posted", "Source"],
        ["Acme", "Intern", "https://example.com/1", "Austin", "open", "2026-08-18", "", "https://board"],
    ]
    rows = records_from_values(values)
    assert rows[0]["link"] == "https://example.com/1"
    assert "Job URL" not in rows[0]


def test_records_from_values_headers_only() -> None:
    assert records_from_values([list(SHEET_HEADERS)]) == []


def test_needs_date_posted_column_detects_legacy_seven_col_header() -> None:
    legacy = [
        "company",
        "title",
        "link",
        "location",
        "status",
        "date_found",
        "source_page",
    ]
    assert needs_date_posted_column(legacy) is True
    assert needs_date_posted_column(list(SHEET_HEADERS)) is False
    assert needs_date_posted_column(["Company", "Title"]) is False


def test_resolve_worksheet_name_defaults_when_env_blank(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_SHEET_WORKSHEET", "")
    assert resolve_worksheet_name() == "Sheet1"
    monkeypatch.delenv("GOOGLE_SHEET_WORKSHEET", raising=False)
    assert resolve_worksheet_name() == "Sheet1"
    assert resolve_worksheet_name("  Internships  ") == "Internships"


def test_resolve_seen_worksheet_name_defaults_when_env_blank(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_SHEET_SEEN_WORKSHEET", "")
    assert resolve_seen_worksheet_name() == "_seen"
    monkeypatch.delenv("GOOGLE_SHEET_SEEN_WORKSHEET", raising=False)
    assert resolve_seen_worksheet_name() == "_seen"
    assert resolve_seen_worksheet_name("  history  ") == "history"


def test_seen_links_needing_backfill_skips_known_and_variants() -> None:
    known = identity_hashes("https://boards.greenhouse.io/spacex/jobs/1")
    inbox = [
        "https://job-boards.greenhouse.io/spacex/jobs/1",
        "https://boards.greenhouse.io/spacex/jobs/2",
        "",
    ]
    assert seen_links_needing_backfill(inbox, known) == [
        "https://boards.greenhouse.io/spacex/jobs/2",
    ]
