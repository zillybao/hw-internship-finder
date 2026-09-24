# AGENTS.md

## Project Overview
A scheduled agent that scans a configured list of company career boards **twice a
day**, detects new internships relevant to embedded/firmware/ASIC/FPGA/RTL work, and
**appends only new rows** to a Google Sheet.

**Stack**: Python 3.11+, `httpx` + `BeautifulSoup` (`lxml` preferred, `html.parser`
fallback), **Google Sheets** via `gspread`, optional Slack webhook, GitHub Actions
cron (`.github/workflows/intern-finder.yml`) or local `python -m src.run`.

There is **no Playwright** and no generic crawler. Almost every live company is an
ATS JSON (or ATS-backed HTML) parser in `src/parse.py`. Fall back to `ats: html`
only when no public API exists.

Sheets is the datastore so you can mark `applied` by hand without fighting a local
CSV. Credentials live in `.env` / `credentials.json` (gitignored), never in the repo.

## Current coverage
- **`config/sites.yaml`**: group 1 live scan list (named ATS parsers only; no `html`
  entries). Do not move companies out of this file.
- **`config/sites_b.yaml`**: group 2 (paused Workday/Arm with intern `query`, plus
  elected adds). Same sheet; second Actions job.
- **`config/sites_paused.yaml`**: archive of the old unfaceted list (not scanned).
- **`config/urls.txt`**: original career-page URL dump (source of truth for *what we
  considered*).
- **`config/urls_skipped.txt`**: companies still needing a dedicated parser. Do not
  scrape these until an ATS/API is identified and `robots.txt`/ToS are checked.

Supported `ats` values: `greenhouse`, `lever`, `ashby`, `workday`, `eightfold`,
`oracle`, `amazon`, `phenom`, `smartrecruiters`, `talentbrew` (alias `smashfly`),
`successfactors`, `icims`, `apple`, `google`, `tesla`, `arm`, `html`.

## Goals
- Poll only the companies listed in `config/sites.yaml` (group 1) or
  `config/sites_b.yaml` (group 2).
- Extract title, canonical link, location, and posting date when the ATS exposes it.
- Match **description body** against `config/keywords.yaml` (not title alone).
- Drop listings whose location is clearly non-US (`config/locations.yaml`).
- Append only *new* postings — never duplicate, never overwrite history, never write
  description text to the sheet or the public page. Never write status, location,
  source page, or credentials to the page.
- Mark previously `open`/`applied` rows `closed` when the link disappears from that
  company’s live intern-titled set. The public page drops `closed` rows and rows
  older than `config/public.yaml` `retain_days`. The sheet row stays.
- Run unattended; a single site failure must not abort the rest. Fail loudly in logs
  (and Slack, if configured).

## Non-Goals
- No auto-apply / form submission.
- No sites that explicitly disallow automated access in `robots.txt` / ToS.
- Not a general-purpose crawler; no URLs except those in `sites.yaml` / `sites_b.yaml`.
- Do not parallelize all companies in one run (rate limits / bot walls).
- Do not fetch a job’s description unless the **title** already looks like intern /
  co-op (or the list payload already includes description text).

## Architecture

```
config/
  sites.yaml              # group 1 companies + ATS + board/host/query/facets
  sites_b.yaml            # group 2 (intern-narrowed Workday/Arm + elected adds)
  sites_paused.yaml       # archive of pre-split unfaceted boards (not scanned)
  keywords.yaml           # description-body keywords
  public.yaml             # public-page retention (retain_days)
  locations.yaml          # US vs non-US location filter
  education.yaml          # post-undergrad / graduate-only drop phrases
  urls.txt                # original URL inventory
  urls_skipped.txt        # not yet parsed
src/
  run.py                  # fetch -> parse -> filter -> dedupe -> sheet
  publish.py              # private sheet -> allowlisted site payload
  fetch.py                # sequential httpx client, retry, split delays
  parse.py                # ATS parsers -> list[JobPosting]
  filter.py               # title noise + US location + date + education + keywords
  dedupe.py               # link normalize + seen-hash cache
  sheet.py                # Google Sheets read/append/mark-closed
  models.py               # JobPosting, SHEET_HEADERS, SCHEMA_VERSION
  notify.py               # optional Slack digest
site/
  index.html              # public table (company, role, link, date, keywords)
  listings.js             # committed sample only; real data is generated into dist/
dist/                     # generated page (gitignored, not committed)
state/
  seen_jobs.json          # local hash cache (gitignored)
  company_runs.json       # per-company run count
logs/
  run-YYYY-MM-DD.log
  skipped-YYYY-MM-DD.log  # intern titles dropped by location, date, education, or keywords
tests/
  fixtures/               # saved HTML for generic parser tests
```

Run locally (project root; do not use an empty `.venv`):

```
python -m src.run --dry-run                         # group 1
python -m src.run --sites config/sites_b.yaml --dry-run
python -m src.run                                   # group 1, write to Google Sheets
python -m src.publish                               # sheet -> dist/, no deploy
```

`--dry-run` does not persist `state/company_runs.json` or `seen_jobs.json`.
It still **reads** the sheet (when credentials exist) so already-written links
are skipped in the preview.

## Methods (how parsing works)
**Prefer the public ATS list API, then intern-title-gate, then description.**

1. **List** jobs from the ATS (JSON). Use intern facets/`query` when the board
   exposes them (Workday `applied_facets` or `query` → CXS `searchText`, Eightfold `filter_seniority`, Amazon
   `query: internship`, Apple `team=internships-…`).
2. **Title-filter** with `title_keywords` (default: `intern`, `internship`,
   `co-op`, `coop`) *before* any per-job detail fetch. Greenhouse list payloads
   omit `content`; do **not** detail-fetch the whole board (SpaceX-scale boards
   are thousands of full-time roles). Skip Greenhouse `?content=true` — the
   payload can be huge and time out; slim list + intern-only details is the
   intended path. If list JSON already has a description (Lever, Ashby, Amazon,
   Phenom, some Eightfold), use it and skip the extra call.
3. **Location-filter** against `config/locations.yaml`. Drop if a foreign country
   is named with no US signal; keep US country/state/`City, ST` forms and
   empty/remote/unknown city-only strings. Workday list `locationsText` is often
   city-only (`Hyderabad`); after the intern detail fetch, append
   `jobPostingInfo.country.descriptor` so it becomes `Hyderabad, India`.
   Eightfold (Infineon) list `locations[0]` is often city-only (`Shanghai`,
   `Linz`); join the rest of `locations` and expand `standardizedLocations`
   ISO codes (`CN`, `AT`) to country names — never leave raw `DE`/`CA` in the
   string (those collide with US states). `foreign_cities` is a backstop for
   unambiguous hubs (Shanghai, Linz, Hyderabad, Munich, …) when country is
   still missing. Do not add US-homonym cities (Cambridge, London, Vancouver).
   If the Workday detail call fails and the city is not listed, city-only stays
   (kept as ambiguous).
4. **Date-filter** dated postings older than **3 days**. Apply this *after*
   computing the live intern-titled set used for closed-status, so an old but
   still-posted intern is not marked closed. Undated postings are kept
   (Google, Tesla, TalentBrew often have no dates).
5. **Education-filter** against `config/education.yaml`. Drop titles that are
   clearly PhD/postdoc internships, and descriptions that require a master’s/PhD
   or already-graduated with no bachelor/undergrad alternative. Keep
   “Graduate Intern” titles and “Bachelor’s or above”.
6. **Keyword-filter** the description in memory against `config/keywords.yaml`
   (token match, so `asic` does not match `basic`). Store the canonical hits on
   `matched_keywords`, then strip `description` before any sheet/cache write.
   Do not write the description or `status` to the public page.
7. **Dedupe** vs sheet rows ∪ `seen_jobs.json` using URL identity hashes
   (normalized link plus host aliases, locale-stripped paths, and ATS req ids).
   After each company, **flush** that company’s new rows and closed-status updates
   to the sheet (and persist `seen_jobs.json` / `company_runs.json`). Do not wait
   until the end of the run — a timeout or crash must keep earlier finds.

Sites are scanned **sequentially** in the YAML list for that job (group 1:
`config/sites.yaml`; group 2: `config/sites_b.yaml`). Delays in `src/fetch.py`:

- JSON ATS (`get_json` / `post_json`): **0.4s** after the previous request finishes
- HTML/SSR (`get_text`: Apple, Google, TalentBrew job pages): **1.5s**

Timeouts retry 3× (transport/timeout only). HTTP 403/404 fail that site and
continue. Expected wall time is **~15–25 min per job** (two sequential Actions
jobs, each with `timeout-minutes: 30`). Unfaceted Workday catalogs and Arm live
in **group 2** (`config/sites_b.yaml`) with intern `query` so they do not share
group 1’s 30-minute cap. On Actions, each job also stops starting new companies
after **26 minutes** (`SCAN_BUDGET_SECONDS`) so `Progress:` / `Done:` lines can
flush. Treat the 30-minute cap as a constraint when adding boards to either file.

Custom / fragile parsers: **Apple** (SSR hydration JSON), **Google**
(`AF_initDataCallback`), **Tesla** (cua-api; often 403 from datacenter IPs).
The unused sitemap helper is `ats: arm`; live Arm (paused) used TalentBrew.

## Data Model
Each posting normalizes to:

| field        | type   | notes |
|--------------|--------|--------|
| company      | str    | from config, not scraped |
| title        | str    | job title |
| link         | str    | canonical URL — primary dedupe key |
| location     | str    | optional, best-effort |
| description       | str    | in-memory only for keyword match; **never written to the sheet or the page** |
| matched_keywords  | list   | canonical keywords that hit the description; comma-separated in column I |
| status            | str    | `open` / `applied` / `closed` — script sets open/closed; `applied` is manual; **never written to the page** |
| date_found   | date   | when this run first kept it |
| date_posted  | date   | optional; ISO, epoch, Workday “Posted N Days Ago”, Amazon `"July 29, 2026"` |
| source_page  | str    | `url` from the site YAML (also the key for closed-status checks) |

Sheet columns (`SCHEMA_VERSION = 2`): `company`, `title`, `link`, `location`,
`status`, `date_found`, `date_posted`, `source_page`, `matched_keywords`.
Headers live in A–I. Append `matched_keywords` as column I; do not insert it
into A–H (a value in Z1 made `append_rows` land in column Z). Pin appends with
`table_range="A1"`. The public page is built from the sheet by `src/publish.py`
and may contain only `company`, `title`, `link`, `date_posted`, and `keywords`.
A second tab `_seen` stores links already shown; wiping the inbox tab does not
revive them.

## Spreadsheet Contract
- Inbox tab (`GOOGLE_SHEET_WORKSHEET`, default `Sheet1`): working queue. Safe to
  clear after you are done with the links.
- `_seen` tab (`GOOGLE_SHEET_SEEN_WORKSHEET`): append-only skip list. Do not
  clear it. Created automatically; inbox links are backfilled on the next write.
- One inbox row per unique normalized `link`.
- Never delete or reorder `_seen` rows the agent added.
- Dedupe key = identity hashes of the link (normalized URL, Greenhouse
  job-boards vs boards, Workday `/en-US/` vs not, req id). Hashes live in
  `state/seen_jobs.json` plus `_seen` ∪ inbox; all three are read each run,
  including `--dry-run`.
- New inbox rows append at the bottom.
- Do not silently reshape existing columns — bump `SCHEMA_VERSION`.
- `GOOGLE_SHEET_ID` may be the raw ID or a
  `https://docs.google.com/spreadsheets/d/<id>/...` URL.
- `GOOGLE_SHEET_WORKSHEET` is the inbox tab name. Blank / unset (including an empty
  GitHub Actions secret) falls back to `Sheet1` — Actions always injects the
  env var when the workflow maps the secret, even if the secret does not exist.

## Keyword Filtering
Keep a posting only if its **description** contains at least one keyword from
`config/keywords.yaml` (case-insensitive **token** match; optional trailing `s`):

`embedded`, `firmware`, `asic`, `fpga`, `rtl`, `mcu`, `microcontroller`

`aliases` in that file collapse other spellings (`micro-controller`,
`microcontrollers`) onto `microcontroller`. Record every canonical hit, in file
order, on the posting before stripping the description.

Tune that file, not `parse.py`. Title-only matching misses “Software Engineering
Intern” roles whose FPGA/RTL work is in the body. Do not use raw substring match
(`asic` is a substring of `basic qualifications`).

Skipped intern titles (no keyword hit, non-US location, older than 3 days, or
post-undergrad-only) go to `logs/skipped-YYYY-MM-DD.log` (company, title, link —
not the description).

**Title noise filter** is separate and runs first: drop non-intern titles so we
never spend HTTP on them. Arm uses a custom `title_keywords` list so `"intern"`
does not match **interconnect**.

**Location filter** (`config/locations.yaml`) runs after the intern title gate
and before date/education/keywords. A US country/state/`City, ST` signal **wins**
over a foreign country in the same string (`US and Canada` is kept). Foreign
country *names* plus `foreign_codes` (UK, GBR, … including office suffixes like
`UK2`) drop a listing only when there is no US signal. `foreign_cities` drops
unambiguous non-US hubs when the ATS omitted the country. Do not put 2-letter
codes that collide with US states (`CA`, `IN`, `DE`, `CO`, `ID`) in
`foreign_codes`, and do not list US-homonym cities. False negatives (missed US
internships) are still worse than a few extra rows — keep empty/unknown-city
locations.

**Date filter:** every run, drop internships whose `date_posted` is older than
3 days. Undated = kept. This no longer depends on `company_runs.json`; a second
scan cannot dump a backlog of month-old jobs that the first lookback skipped.
Prefer original posted/created timestamps over `updated_at` so an old listing
that was edited yesterday is still dropped.

**Education filter** (`config/education.yaml`): conservative. Tune phrases from
skipped/new-row logs. Do not drop on the word “graduate” alone.

**Log-only buffer:** `first_seen_runs: 0` on current sites, so keyword misses
are dropped immediately. `--dry-run` is the way to preview a write.

## Status Tracking
Each run, intern-titled links still live on that `source_page` are the “open”
set. Sheet rows for that source with status `open` or `applied` whose normalized
link is missing are set to `closed` (row kept). Never move `applied` back to
`open`. Closed-status uses the title-filtered live set, not the keyword/date/education-filtered
set — a still-posted intern that fails later filters is not marked closed.
The public page drops `closed` rows and rows older than `retain_days`.
`applied` is not copied to the page; the role stays listed until it is closed
or expires.

## Reliability & Site Health
- Sequential requests only; split JSON vs HTML delays (see Methods).
- Real User-Agent in `fetch.py` (not the default Python UA).
- Per-company sheet flush so Actions timeouts still keep high-priority finds.
- `expected_min` on a site: if intern-titled parse count is below that, log a
  warning (possible API/facet break). Many quieter companies use `expected_min: 0`.
- Before adding a company: check `robots.txt` / ToS; prefer a public JSON
  endpoint (Network tab) over CSS selectors; add group 1 companies to
  `sites.yaml` in the matching priority tier, group 2 companies to
  `sites_b.yaml` — do not hardcode companies in `parse.py`.

## Review Workflow
Primary review is the sheet, roughly daily (newest rows at the bottom). `status`
is `open` / `applied` / `closed`. Optional Slack (`SLACK_WEBHOOK_URL`) posts a
short end-of-run digest of new rows and of per-site failures; it is not required.

## Scheduling
- Cadence: 2 workflow runs/day. Cron: `0 8,20 * * *` UTC. Each run is two
  sequential scan jobs (group 1 then group 2), same sheet, then a separate
  Pages job that deploys the allowlisted table. A Pages failure does not fail
  the sheet scans. Generated `dist/` is not committed.
- Each job is a **full scan** of that group’s YAML (idempotent writes).
- Prefer GitHub Actions or cron over an always-on process.
- Actions does not read `.env`. Required repo secrets: `GOOGLE_SERVICE_ACCOUNT_JSON`
  (full key file contents) and `GOOGLE_SHEET_ID`. Optional: `GOOGLE_SHEET_WORKSHEET`,
  `SLACK_WEBHOOK_URL`.
- The workflow maps scanner exit `1` (some boards failed) to a warning and a green
  job, because Tesla/Apple/Google often 403 from GitHub IPs and new rows are still
  written. Exit `2` (sheet unavailable) still fails the job.

## Config Conventions (`config/sites.yaml`)
```yaml
- company: Example Corp
  ats: greenhouse          # required; see supported values above
  board: examplecorp       # ATS slug / Workday site / Oracle siteNumber
  url: https://boards.greenhouse.io/examplecorp
  expected_min: 1          # warn if intern-titled count drops below this
  first_seen_runs: 0       # 0 = always enforce keywords (no log-only keep)
  # Workday extras: workday_host, workday_tenant, applied_facets, query (searchText)
  # Eightfold extras: domain, eightfold_api (v2|pcsx), query, extra_params
  # Oracle extras: oracle_host, board, query
  # SuccessFactors extras: url is the RMK search root (may include /Teradyne)
  # iCIMS extras: url is https://careers-*.icims.com; query is searchKeyword
  # title_keywords: override intern/co-op title gate (see Arm)
```

- Add companies here, not in `parse.py`. Place them in the matching scan-order
  tier comment block (core semi → solid ATS → quiet → slow/fragile last).
- Prefer intern `applied_facets` / `query` on large Workday/Eightfold/Phenom
  boards so we do not paginate the full catalog. Do not invent Workday facet IDs.
- Conservative title/`query` filters: false negatives (missed internships) are
  worse than a few extra rows to skim — except Arm-style substring traps.

## Error Handling
- One site failing (timeout, 403, layout change) must not crash the run.
- Log `{company}: {exception}` and continue. Exit `1` if any site failed (rows
  from successful sites are still written), `2` if the sheet is unavailable
  (non-dry-run), `0` on a clean run.
- Slack failure digest if `SLACK_WEBHOOK_URL` is set. Repeated-failure tracking
  across runs is not implemented.

## Coding Conventions
- Type-hint everything; `JobPosting` is a dataclass in `src/models.py`.
- No secrets in the repo.
- Keep parsers unit-testable with fake fetchers / fixtures (no network in
  `tests/`). Title-gate and date-parsing belong in those tests.

## Testing
```
python -m pytest
```
Cover link normalization, identity-hash dedupe (Greenhouse host aliases, Workday
locale/req ids, HYPERLINK cells), keyword token match, US location filter, 3-day posted-date
lookback, education filter, Greenhouse intern-only detail fetches,
TalentBrew card HTML, Workday `searchText` from `query`, SuccessFactors/iCIMS intern-only
details, Amazon-style dates, spreadsheet-ID extraction from a
docs URL, blank `GOOGLE_SHEET_WORKSHEET` → `Sheet1`, per-company sheet flush
(cache advances only after a successful append), keyword alias collapse, the
public-page allowlist (no status, description, location, or source page), and
column I appended without shifting A–H.

## Posted-date lookback
Every run drops internships with `date_posted` older than **3 days**. Undated
postings are treated as “found today” (kept). Google, Tesla, and TalentBrew often
have no dates — lookback will not shrink those boards. Amazon English dates
(`July 29, 2026`) are parsed. Workday `startDate` is the posting start (used when
`postedDate` is missing). Eightfold `postedTs=0` is treated as unknown, not 1970.
Greenhouse uses `created_at` (not `updated_at`) so a refreshed old req is dropped.

`first_seen_runs` counts successful-or-failed attempts once state is saved (not
on `--dry-run`). With `first_seen_runs: 0` it does not keep keyword misses.

## Education filter (post-undergrad)
v1 is phrase-based and conservative (`config/education.yaml`):

- Drop titles like `PhD Intern` / `postdoctoral`.
- Drop descriptions that require a master’s/PhD or already-graduated **unless**
  a bachelor/undergrad phrase is also present (`Bachelor's or above`, `BS/MS`).
- Do **not** drop `Graduate Intern` titles (often BS seniors).

Follow-ups (tune from skipped logs, do not broaden blindly):

- Add company-specific “join as / student type” fields when an ATS exposes them
  (Infineon `custom_JD.join_as` is already `Student/Intern` on intern reqs).
- Watch false drops on “pursuing a master’s” in combined BS/MS postings that
  forgot to say bachelor; add an undergrad_ok phrase rather than deleting the
  graduate_required line.
- Leave “new graduate” full-time-disguised-as-intern for a later pass if logs
  show it.

## Open Questions / TODO
- Tune `expected_min` and lookback from skipped/new-row logs after more runs.
- MediaTek / MaxLinear / Siemens DISW / Wind River still lack a confirmed public
  list API (`config/urls_skipped.txt`).
- Lattice Semiconductor is still live Workday without `applied_facets` (group 1).
- Tesla/Apple/Google bot walls from Actions IPs.
- Optional: intern `query` on Phenom; real intern facets on large Workday boards
  once confirmed in the Network tab.
