"""Page-only graduate catalog: sheet stays clear, page can still list them."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.filter import filter_by_education, load_education_filter
from src.models import JobPosting
from src.public_extra import PublicExtraCatalog, sync_graduate_catalog

EDUCATION_YAML = Path(__file__).resolve().parent.parent / "config" / "education.yaml"
TODAY = date(2026, 9, 22)
SOURCE = "https://example.com/careers"


def _grad(description: str, *, link: str = "https://example.com/jobs/grad") -> JobPosting:
    return JobPosting(
        company="Acme",
        title="Firmware Intern",
        link=link,
        source_page=SOURCE,
        description=description,
        date_posted=date(2026, 9, 20),
    )


def test_masters_keyword_hit_is_page_only_not_sheet(tmp_path: Path) -> None:
    rules = load_education_filter(EDUCATION_YAML)
    posting = _grad("Master's required. Work on FPGA bring-up.")
    undergrad, grad_only = filter_by_education([posting], rules)
    catalog = PublicExtraCatalog(tmp_path / "public_extra.json")
    kept, missed = sync_graduate_catalog(
        catalog,
        source_page=SOURCE,
        live_links={posting.link},
        grad_only=grad_only,
        keywords=["fpga", "firmware"],
        aliases=None,
        today=TODAY,
    )

    assert undergrad == []
    assert missed == []
    assert [item.link for item in kept] == [posting.link]
    catalog.save()
    loaded = PublicExtraCatalog.load(catalog.path)
    record = loaded.listings[0]
    assert record["keywords"] == ["fpga"]
    assert "description" not in record
    assert "status" not in record
    assert record["source_page"] == SOURCE


def test_grad_keyword_miss_is_in_neither_sheet_nor_catalog(tmp_path: Path) -> None:
    rules = load_education_filter(EDUCATION_YAML)
    posting = _grad("Master's required. Marketing and analytics.")
    undergrad, grad_only = filter_by_education([posting], rules)
    catalog = PublicExtraCatalog(tmp_path / "public_extra.json")
    kept, missed = sync_graduate_catalog(
        catalog,
        source_page=SOURCE,
        live_links={posting.link},
        grad_only=grad_only,
        keywords=["fpga"],
        aliases=None,
        today=TODAY,
    )
    assert undergrad == []
    assert kept == []
    assert [item.link for item in missed] == [posting.link]
    assert catalog.listings == []


def test_missing_live_link_drops_only_that_company_after_sync(tmp_path: Path) -> None:
    catalog = PublicExtraCatalog(tmp_path / "public_extra.json")
    gone = _grad("Master's required. FPGA.", link="https://example.com/jobs/gone")
    other = JobPosting(
        company="Other",
        title="RTL Intern",
        link="https://example.com/jobs/stay",
        source_page="https://example.com/other",
        description="Master's required. RTL design.",
        date_posted=date(2026, 9, 20),
    )
    sync_graduate_catalog(
        catalog,
        source_page=SOURCE,
        live_links={gone.link},
        grad_only=[gone],
        keywords=["fpga"],
        aliases=None,
        today=TODAY,
    )
    sync_graduate_catalog(
        catalog,
        source_page=other.source_page,
        live_links={other.link},
        grad_only=[other],
        keywords=["rtl"],
        aliases=None,
        today=TODAY,
    )
    assert len(catalog.listings) == 2

    sync_graduate_catalog(
        catalog,
        source_page=SOURCE,
        live_links=set(),
        grad_only=[],
        keywords=["fpga"],
        aliases=None,
        today=TODAY,
    )
    assert [item["link"] for item in catalog.listings] == [other.link]


def test_live_role_outside_this_runs_grad_set_stays_in_catalog(tmp_path: Path) -> None:
    catalog = PublicExtraCatalog(tmp_path / "public_extra.json")
    posting = _grad("Master's required. FPGA.")
    sync_graduate_catalog(
        catalog,
        source_page=SOURCE,
        live_links={posting.link},
        grad_only=[posting],
        keywords=["fpga"],
        aliases=None,
        today=TODAY,
    )
    sync_graduate_catalog(
        catalog,
        source_page=SOURCE,
        live_links={posting.link},
        grad_only=[],
        keywords=["fpga"],
        aliases=None,
        today=TODAY,
    )
    assert [item["link"] for item in catalog.listings] == [posting.link]
