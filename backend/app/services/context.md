# Context: PAGASA Bulletin Scraper & Parser — Code Review

## Current status — 2026-09-26

**PARTIALLY FIXED — FOLLOW-UP REQUIRED**, reviewed at `eafc2c6` on `fabio/backend/bulletin-scraper-review`.

Use the [current handoff and open checklist](../../../docs/bulletin-refactor-status.md) to resume work. The 16 existing bulletin tests pass, but confirmed defects remain. Commit messages claiming all findings are addressed do not represent the latest review result.

The original review and testing checklist below are historical context, not the current completion checklist. In particular, the old expectation that upstream failures return an empty list is superseded by follow-up F07 in the current handoff.

## Branch
`fabio/backend/bulletin-scraper-review` (branched from `develop`)

## Review Date
2026-09-26

## Scope
This review covers the backend logic responsible for:
1. Scraping the PAGASA bulletin index page for active tropical cyclone PDF links
2. Downloading those PDFs and saving them to a temporary directory
3. Parsing meteorological metadata (typhoon name, bulletin number, coordinates, wind speeds, signal areas) from extracted PDF text using regex
4. Persisting parsed bulletin and signal data into a PostGIS database via SQLAlchemy

### Files Under Review
| File | Role |
|------|------|
| `backend/app/services/bulletin_parser.py` | Core scrape, parse, and DB-save logic |
| `backend/app/api/bulletins.py` | FastAPI router — `/parse`, `/upload`, `/`, `/{id}/signals` |
| `backend/tests/test_bulletin_parser.py` | Existing unit tests |

---

## Review Prompt
> **Goal:** Review backend logic for scraping and parsing the PAGASA bulletin directory.
>
> **Requirements:**
> - Check for robustness in the HTML fetching and regex/parsing logic.
> - Identify any potential performance bottlenecks or memory leaks, especially if handling large PDF downloads or frequent requests.
> - Ensure proper error handling (e.g., handling network timeouts, missing elements, or malformed HTML) without silently swallowing exceptions.
> - Verify that the code follows standard naming conventions and backend best practices.
>
> **Constraints:**
> - Do not suggest adding heavy external scraping frameworks unless absolutely necessary; keep the logic lightweight.
> - Ensure the solution avoids overwhelming the target server (e.g., rate limiting or caching suggestions are welcome).
> - Do not change the overall architecture or API response shapes unless there is a critical flaw.

---

## Issues Found (Summary)

### 🔴 Critical (6)
| # | Location | Description |
|---|----------|-------------|
| C1 | `bulletin_parser.py` L135 | `func` (SQLAlchemy) never imported → `NameError` crash on every DB save |
| C2 | `bulletin_parser.py` L51–57 | No try/except in `download_bulletin_pdf` → network errors propagate unhandled |
| C3 | `bulletins.py` L50–65 | Temp PDF not cleaned up when `parse_bulletin_text` or `save_bulletin_to_db` raises |
| C4 | `bulletin_parser.py` L75–80 | Typhoon name regex `[A-Z\s\-]+` greedily over-captures across line boundaries |
| C5 | `bulletin_parser.py` L95–96 | Silent `0.0, 0.0` fallback for missing coordinates — stored as a valid GIS point |
| C6 | `bulletin_parser.py` L188 | `island_group` hardcoded to `2` (Mindanao) for every signal record |

### 🟡 Performance & Security (6)
| # | Location | Description |
|---|----------|-------------|
| P1 | `bulletin_parser.py` L55 | Entire PDF buffered in RAM via `response.content` — should use chunked streaming |
| P2 | `bulletins.py` L48 | No deduplication check — re-downloads every PDF on each `/parse` trigger |
| P3 | `bulletins.py` L48 | No delay between sequential PDF downloads — risk of flooding PAGASA server |
| P4 | `bulletins.py` L36 | `POST /bulletins/parse` has no rate limiting or cooldown guard |
| P5 | `bulletins.py` L12 | `TEMP_DIR = "temp_bulletins"` is a relative path — unstable across launch dirs |
| P6 | `bulletins.py` L74 | Manual upload endpoint has no file size validation |

### 🟢 Refactoring (5)
| # | Location | Description |
|---|----------|-------------|
| R1 | `bulletins.py` L22–33 | N+1 query in `GET /bulletins/` — use `joinedload` |
| R2 | Both files | `print()` used for error logging — replace with `logging` module |
| R3 | `bulletin_parser.py` L176 | O(n×m) string matching against all `AdminBoundary` rows in Python |
| R4 | `bulletin_parser.py` L146 | Multiple intermediate `db.commit()` calls risk partial state on failure |
| R5 | `bulletin_parser.py` L118 | Category only checks for "typhoon" — misses Severe Tropical Storm and Tropical Depression |

---

## Testing Checklist

### Unit Tests — `test_bulletin_parser.py`

- [ ] **T-U1** — Existing test passes with `func` import fix applied
- [ ] **T-U2** — Test typhoon name extraction with quoted name: `TYPHOON "LEON"` → `LEON`
- [ ] **T-U3** — Test typhoon name extraction without quotes: `TYPHOON LEON` → `LEON`
- [ ] **T-U4** — Test name regex does NOT over-capture: name field must not contain `\n` or keywords like `MAXIMUM`
- [ ] **T-U5** — Test coordinate parsing with `°N, °E` format → correct float values
- [ ] **T-U6** — Test coordinate parsing with plain `N, E` format → correct float values
- [ ] **T-U7** — Test coordinate parsing when absent → returns `None` (not `0.0`)
- [ ] **T-U8** — Test bulletin_count extraction from `Bulletin No. X` → correct integer
- [ ] **T-U9** — Test signal block segmentation: Signal No. 3 and Signal No. 2 correctly partitioned
- [ ] **T-U10** — Test category returns `"Severe Tropical Storm"` when STS keyword is present
- [ ] **T-U11** — Test category returns `"Tropical Depression"` when TD keyword is present
- [ ] **T-U12** — Test `get_island_group()` returns `0` for a Luzon province
- [ ] **T-U13** — Test `get_island_group()` returns `1` for a Visayas province
- [ ] **T-U14** — Test `get_island_group()` returns `2` for a Mindanao province

### Integration Tests — `BulletinParserService`

- [ ] **T-I1** — `fetch_active_bulletin_links()` with mocked 200 response returns only `.pdf` links containing "bulletin"
- [ ] **T-I2** — `fetch_active_bulletin_links()` with mocked non-200 response returns empty list
- [ ] **T-I3** — `fetch_active_bulletin_links()` with mocked network timeout logs error and returns empty list
- [ ] **T-I4** — `fetch_active_bulletin_links()` correctly resolves relative PDF links to absolute URLs
- [ ] **T-I5** — `download_bulletin_pdf()` with mocked 200 response streams and writes file correctly
- [ ] **T-I6** — `download_bulletin_pdf()` with mocked 404 raises `RuntimeError` with HTTP status in message
- [ ] **T-I7** — `download_bulletin_pdf()` with mocked timeout raises `RuntimeError` (not hangs)
- [ ] **T-I8** — `download_bulletin_pdf()` URL with no `.pdf` suffix raises `ValueError`
- [ ] **T-I9** — `save_bulletin_to_db()` does NOT crash when `func` is imported correctly
- [ ] **T-I10** — `save_bulletin_to_db()` with `latitude=None` creates `TropicalCycloneBulletin` with `center_geom=None`
- [ ] **T-I11** — `save_bulletin_to_db()` is idempotent — re-saving the same bulletin count does not create a duplicate
- [ ] **T-I12** — `save_bulletin_to_db()` assigns correct `island_group` per province after fix

### API Endpoint Tests — `bulletins.py`

- [ ] **T-A1** — `POST /api/bulletins/parse` with no active PDFs returns `404`
- [ ] **T-A2** — `POST /api/bulletins/parse` with mocked links processes all and returns `parsed_count`
- [ ] **T-A3** — `POST /api/bulletins/parse` — temp file is cleaned up even when parsing one PDF fails
- [ ] **T-A4** — `POST /api/bulletins/upload` with a `.pdf` file returns `200` and bulletin metadata
- [ ] **T-A5** — `POST /api/bulletins/upload` with a non-`.pdf` file returns `400`
- [ ] **T-A6** — `POST /api/bulletins/upload` — temp file is cleaned up on parse failure and returns `500`
- [ ] **T-A7** — `GET /api/bulletins/` returns list without triggering N+1 queries (verify with SQLAlchemy echo)
- [ ] **T-A8** — `GET /api/bulletins/{id}/signals` returns correct signal level and area_name

### Manual / Environment Tests

- [ ] **T-M1** — Start uvicorn from a different working directory; confirm `TEMP_DIR` resolves correctly after fix
- [ ] **T-M2** — Trigger `POST /parse` twice in quick succession; confirm second call is short-circuited (deduplication)
- [ ] **T-M3** — Simulate PAGASA server returning a 503; confirm error is logged and endpoint returns graceful response
- [ ] **T-M4** — Upload a known PAGASA bulletin PDF via `/upload`; verify DB record has correct typhoon name, coordinates, and signal areas
- [ ] **T-M5** — Verify no orphaned files remain in temp directory after a failed parse cycle

---

## Fix Priority Order (Recommended)
1. **C1** — Import `func` (zero-risk, 1-line fix; unblocks all DB save tests)
2. **C3** — Wrap per-link loop in `try/finally` for temp file cleanup
3. **C2** — Add error handling + streaming to `download_bulletin_pdf`
4. **C5** — Change coord fallback from `0.0` to `None`; guard geometry creation
5. **C6** — Implement `get_island_group()` helper using province mapping
6. **C4** — Tighten typhoon name regex to prefer quoted match
7. **R1** — Apply `joinedload` to `GET /bulletins/`
8. **R2** — Replace `print()` with `logging`
9. **P1** — Switch to `client.stream()` for PDF download
10. **P2/P3** — Add deduplication check and `asyncio.sleep(1)` between downloads
11. **R4** — Consolidate to single `db.commit()` per `save_bulletin_to_db` call
12. **R5** — Fix category classification regex
13. **P4–P6** — Rate limiting, absolute TEMP_DIR, upload size guard
