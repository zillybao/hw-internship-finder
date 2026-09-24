# Intern Finder

A public table of **embedded / firmware / ASIC / FPGA / RTL** internships, and the scanner that keeps it current. GitHub Pages shows company, role, apply link, date posted, and the keywords that matched. The same scan still appends new rows to a private Google Sheet.

There is no Playwright and no generic crawler. Each company in `config/sites.yaml` (group 1) or `config/sites_b.yaml` (group 2) uses a named ATS parser (Greenhouse, Workday, Lever, …). You mark `applied` by hand in the sheet. That status never appears on the public page.

## Public page

Visitors see listings that are still open and inside the retention window. A row leaves the page when either:

- the company drops the posting (the scanner marks the sheet row `closed`), or
- it is older than `retain_days` in `config/public.yaml` (default **14**), measured from `date_posted`, or from `date_found` when the board has no date.

The sheet row stays. Rows already in the sheet before matched keywords were stored do not appear, because descriptions are never saved and the keyword cannot be reconstructed.

Preview locally without deploying:

```bash
python -m src.publish
python -m http.server -d dist
```

Open `http://127.0.0.1:8000/`. `site/index.html` is the same layout with fake sample rows (`python -m http.server -d site`).

The live URL exists only after this workflow is on the default branch and **Settings → Pages → Source → GitHub Actions** is turned on.

### Public vs private

| On the page | Stays private |
|-------------|---------------|
| company, role, apply link, date posted, matched keywords, updated time | Google Sheet, `applied` / `closed` status, location, description, `source_page` |
| company list and keyword config in this repo | service-account JSON, sheet id, Slack webhook, `.env`, `credentials.json`, `state/`, `logs/` |

Do not commit secrets. A fork should use its own spreadsheet and its own Actions secrets. Share the sheet only with the service account, not “anyone with the link.”

## What it does

- Scans group 1 (`config/sites.yaml`) then group 2 (`config/sites_b.yaml`) on GitHub Actions (sequential HTTP, public ATS JSON where possible). Both write the same sheet.
- Title-gates on intern / co-op **before** fetching descriptions.
- Drops postings whose location is clearly non-US (`config/locations.yaml`). Empty / remote / unknown city-only locations are kept; known foreign hubs (Shanghai, Linz, …) are dropped even without a country name.
- Drops dated postings older than 3 days. Undated postings are kept.
- Drops graduate-only internships from the sheet when `config/education.yaml` says `sheet: skip`. Keyword matches among those skips are still shown on the public page. Set `sheet: include` to append them to the sheet instead.
- Keeps a posting only if the description matches a keyword in `config/keywords.yaml` (token match, so `asic` does not match `basic`). The matched keywords are stored on the new sheet row and shown on the public page. Spelling variants such as `micro-controller` collapse to `microcontroller`.
- Dedupes on the canonical job link. New matches are flushed to the sheet after each company (so a timeout still keeps earlier finds); history is never overwritten.
- Marks previously `open` / `applied` rows `closed` when that link disappears from the company’s live intern-titled set. Closed and expired rows drop off the public page on the next publish. A failed company scan does not mark that company closed.
- Optional Slack digest of new rows and per-site failures.

It does **not** auto-apply, scrape sites outside `sites.yaml` / `sites_b.yaml`, or write description text to the sheet or the public page. Status and credentials stay off the page.

## Requirements

- Python 3.11+
- A Google Cloud **service account** with access to your spreadsheet
- Optional: a Slack incoming webhook

## Setup

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Use a native Windows Python (not MSYS2) so `pip` can install wheels. `.env` and `credentials.json` are gitignored; GitHub Actions never reads them — use **repo secrets** for CI (below).

### Google Sheets

This is a **service account**, not OAuth as you. Share the spreadsheet with that robot email, then put its JSON key and the sheet ID in `.env` (local) or GitHub secrets (Actions).

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and enable **Google Sheets API** and **Google Drive API** (Drive is required so `gspread` can open the file by ID).
2. **IAM & Admin → Service accounts → Create service account.** Skip a GCP IAM role; access comes from sharing the sheet. **Keys → Add key → JSON**, save as `credentials.json` in the project root.
3. Open that JSON and copy `client_email` (`…@….iam.gserviceaccount.com`). In Google Sheets, **Share** that address as **Editor**. Uncheck “Notify people” (it is not a real inbox).
4. Copy `.env.example` to `.env` and set the spreadsheet ID (the token after `/d/` in the docs URL, or the full URL):

```
GOOGLE_SERVICE_ACCOUNT_FILE=credentials.json
GOOGLE_SHEET_ID=your-spreadsheet-id-or-url
# GOOGLE_SHEET_WORKSHEET=Sheet1
# SLACK_WEBHOOK_URL=
```

Leave the tab named `Sheet1`, or set `GOOGLE_SHEET_WORKSHEET` to the exact tab name. A blank value also falls back to `Sheet1`. If `GOOGLE_SERVICE_ACCOUNT_JSON` is set (the full key JSON as one string), it is used instead of the file.

The scanner also creates a `_seen` tab in the same spreadsheet. That tab is the skip list. **Clear the inbox tab when you are done with links; leave `_seen` alone** so the same roles are not appended again.

Sheet columns (written automatically if row 1 is empty):

| company | title | link | location | status | date_found | date_posted | source_page | matched_keywords |
|---------|-------|------|----------|--------|------------|-------------|-------------|------------------|

`link` is the job posting (dedupe key). `source_page` is the career-board URL from the site YAML (used for closed-status). `status` is `open` or `closed` from the scanner; set `applied` yourself. `matched_keywords` is the comma-separated list that hit the description. Newest rows are at the bottom. Leave row 1 as headers in A–I only. An existing A–H header row gets column I added in place; A–H are not shifted.

## Run

From the project root (do not use an empty `.venv`):

```bash
python -m src.run --dry-run    # group 1: fetch + filter, no sheet or state writes
python -m src.run              # group 1: write to Google Sheets
python -m src.run --sites config/sites_b.yaml --dry-run
python -m src.publish         # private sheet -> dist/ (no deploy)
python -m pytest
```

`--dry-run` is the way to preview a write (no sheet or `state/` writes). If credentials are present it still **reads** the inbox and `_seen` tabs so roles already stored there are not listed as new. Dated postings older than **3 days** are dropped every run; undated postings are kept. Keywords and the education filter are enforced immediately (`first_seen_runs: 0`).

New rows are flushed after each company. Typical wall time is **15–25 minutes per group**. A single site failure is logged and the rest continue. Exit codes: `0` clean, `1` some sites failed (rows still written), `2` sheet unavailable (non-dry-run).

Logs:

- `logs/run-YYYY-MM-DD.log` — full run (`parsed`, `non-US`, `kept after keywords`, `new`)
- `logs/skipped-YYYY-MM-DD.log` — intern titles dropped by the US-location, 3-day date, education, or keyword filter

## GitHub Actions

[`.github/workflows/intern-finder.yml`](.github/workflows/intern-finder.yml) runs twice a day (`0 8,20 * * *` UTC ≈ 4am / 4pm EDT) and on `workflow_dispatch`. Cron is UTC and not DST-aware (those slots are 3am / 3pm Eastern in EST). GitHub may start the job later than the cron minute.

The workflow does **not** load `.env` or `credentials.json` from the repo (both are gitignored). GitHub does not infer secret meaning from names: you create secrets with **these exact names**, the workflow copies them into env vars of the same name, and `src/sheet.py` / `src/notify.py` read them with `os.getenv`.

**Settings → Secrets and variables → Actions → New repository secret.** Add:

| Secret | Required | Value to paste |
|--------|----------|----------------|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | yes | Entire contents of `credentials.json` (one JSON object, including `private_key` and `client_email`) |
| `GOOGLE_SHEET_ID` | yes | Same spreadsheet ID or docs URL as local `.env` |
| `GOOGLE_SHEET_WORKSHEET` | no | Inbox tab name. Omit or leave blank to use `Sheet1` |
| `GOOGLE_SHEET_SEEN_WORKSHEET` | no | Skip-list tab. Omit to use `_seen`. Do not clear this tab |
| `SLACK_WEBHOOK_URL` | no | Incoming webhook URL for new-posting / failure digests |

The JSON secret is written to `credentials.json` on the runner; the scan step then sets `GOOGLE_SERVICE_ACCOUNT_FILE=credentials.json`. Same service account, same shared spreadsheet as local runs.

If some career boards 403 (Tesla / Apple / Google often do from GitHub IPs), the scanner exits `1` but still writes any new rows. The workflow treats that as a **warning** and keeps the job green. Exit `2` (sheet unavailable / missing secrets) still fails the job.

After **Run scanner**, the **Report planned sheet writes** step prints the last
`Progress: added=… closed=… last=… elapsed=…` line (running totals after each
company flush), any per-company `flushed added=` lines, and `Done: added=…` if
the scan finished. Rows are appended **as each company completes**, so a timeout
does not mean zero writes — it means the run never reached the final `Done:`
line. `added=0` with a Progress line usually means nothing new, not a silent
write failure.

The workflow caches `state/` (`seen_jobs.json`, `company_runs.json`) between jobs and runs. Job timeout is 30 minutes **per group**; the scanner stops starting new companies after 26 minutes on Actions. Group 1 is `config/sites.yaml`. Group 2 is `config/sites_b.yaml` (intern-narrowed Workday/Arm plus elected adds). Both jobs write the same spreadsheet. `config/sites_paused.yaml` is an archive and is not scanned.

After both scan jobs, **Public page** reads the sheet and deploys `dist/` with GitHub Pages. That job has its own token (`contents: read`, `pages: write`) and does not commit generated listings. If Pages is not enabled, or the deploy fails, the sheet scans are already finished and stay green. Turn on **Settings → Pages → Source → GitHub Actions** when you want the URL.

## Config

**Companies** — add group 1 entries to `config/sites.yaml` and group 2 entries to `config/sites_b.yaml`, not to parser code. Supported `ats` values: `greenhouse`, `lever`, `ashby`, `workday`, `eightfold`, `oracle`, `amazon`, `phenom`, `smartrecruiters`, `talentbrew` (alias `smashfly`), `successfactors`, `icims`, `apple`, `google`, `tesla`, `arm`, `html`.

```yaml
- company: Example Corp
  ats: greenhouse
  board: examplecorp
  url: https://boards.greenhouse.io/examplecorp
  expected_min: 1
  first_seen_runs: 0
```

Before adding a company: confirm `robots.txt` / ToS, prefer a public JSON list API, and use intern facets/`query` on large Workday / Eightfold / Phenom boards. Companies still waiting on a parser live in `config/urls_skipped.txt`.

**Keywords** — edit `config/keywords.yaml`. A posting is kept if the description contains any of: `embedded`, `firmware`, `asic`, `fpga`, `rtl`, `mcu`, `microcontroller`. Matching is case-insensitive **token** match on the **body**, not the title (plurals like `ASICs` still count). `aliases` map other spellings onto those names.

**Graduate roles** — edit `sheet` in `config/education.yaml`. This is the switch for a clone:

- `skip` (this repo’s default): do not append graduate-only roles. That means a PhD/doctoral title, or a description that requires a master’s/PhD or an already-finished degree and never offers a bachelor’s path. “Graduate Intern” and “Bachelor’s or above” are still written. Keyword-matching graduate roles still show on the public page. They are not added to the sheet or the `_seen` tab.
- `include`: append those roles when they also match the US location, 3-day date, and keyword filters. The page then gets them from the sheet.

Change that one line. Leave `title_drop` and `graduate_required` as they are; those lists are the definition of graduate-only.

**Public retention** — edit `retain_days` in `config/public.yaml`. This only affects the page. The sheet is not cleared when a listing expires.

**Locations** — edit `config/locations.yaml`. Drop listings that name a foreign country with no US signal; a US country/state/`City, ST` match wins (`US and Canada` is kept). Keep ambiguous/empty locations. Location stays on the sheet and is not on the public page.

## Layout

```
config/sites.yaml      # group 1 companies + ATS + board/host/query/facets
config/sites_b.yaml    # group 2 (Actions job 2)
config/keywords.yaml   # description-body keywords and spelling aliases
config/public.yaml     # how long listings stay on the public page
config/locations.yaml  # US vs non-US location filter
config/urls.txt        # original career-page inventory
config/urls_skipped.txt
src/run.py             # fetch → parse → filter → dedupe → sheet
src/publish.py         # private sheet → allowlisted dist/listings.js
src/parse.py           # ATS parsers
site/                  # static page; sample listings.js is fake
dist/                  # generated page (gitignored)
state/                 # seen hashes, run counts, page-only graduate catalog (gitignored)
logs/
```

Agent-oriented design notes live in [`AGENTS.md`](AGENTS.md). 