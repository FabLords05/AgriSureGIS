# PAGASA API refactor — review handoff

**Status: PARTIALLY FIXED — FOLLOW-UP REQUIRED**

- Review date: 2026-09-26
- Branch: `fabio/backend/bulletin-scraper-review`
- Reviewed implementation: `eafc2c6` (following `e37e1fe`)
- Next action: address the open checklist below, add regression coverage, and request another review.
- Completion: pending; do not mark the refactor done based only on the passing tests or previous commit messages.

## Verified progress

The current code uses unique temporary paths for uploads/downloads, bounds the upload read, rolls back failed persistence in the endpoints, cleans up ordinary download failures, and resolves relative PDF links with `urljoin`. It stamps the cooldown before its first await and distinguishes new database rows from existing rows when counting parsed bulletins.

All **16 existing bulletin tests passed** during the review. Additional checks used mocked PDF extraction, HTTP responses, and database sessions; they reproduced the failures recorded below. No live PAGASA/PostGIS integration was verified. The review did not modify source files or database records.

## Open checklist

Start with F01–F07 because they affect stored data and visible error handling. Keep the implementation lightweight and preserve the existing architecture and response shapes unless a critical flaw requires a coordinated change.

- [ ] **F01 — Search for the signal terminator after the signal block.** In `parse_bulletin_text`, `_POST_SIGNAL_SECTION.search(text)` can match a header before the signal table and make the final block empty. Reproduction: a `FORECAST POSITIONS` section before `SIGNAL NO. 2` and `SIGNAL NO. 1` causes the last signal's text to disappear. Search forward from the final signal marker. Verify the actual closing section is excluded while all signal areas remain.
- [ ] **F02 — Resolve whole-province signal declarations.** `save_bulletin_to_db` currently requires both province and municipality names to appear in the text. `SIGNAL NO. 2\nLuzon: Batanes` with a `Batanes/Basco` boundary commits no signal rows. Distinguish whole-province declarations from restricted municipality clauses, and scope municipality matching to its province. Verify both inclusion and exclusion cases to prevent false assignments.
- [ ] **F03 — Validate storm names on the storm heading.** `TYPHOON “LEON”` currently fails identity validation; `TYPHOON\nmaximum sustained winds of 155 km/h` is accepted with the name `maximum`. Support typographic quotes and prevent the unquoted fallback from crossing lines or accepting narrative text. Verify a missing name is rejected before persistence.
- [ ] **F04 — Parse parenthesized coordinates.** `(16.2°N, 123.5°E)` returns `None` for both coordinates because the degree-symbol branch requires a preceding `at`. Support this format while retaining the existing formats and explicit handling of genuinely absent coordinates.
- [ ] **F05 — Correct Cordillera island groups.** `Abra`, `Apayao`, `Benguet`, `Ifugao`, `Kalinga`, and `Mountain Province` are missing from `LUZON_PROVINCES`; all currently return Mindanao (`2`). Add them and cover every listed province with assertions for Luzon (`0`).
- [ ] **F06 — Persist source issuance, expiry, and year.** `save_bulletin_to_db` still sets issuance/expiry to ingestion time and uses the current year for the storm. Parse the source timestamps and derive the storm year consistently from issuance. Test a historical upload and timezone conversion; do not silently invent source dates when parsing fails.
- [ ] **F07 — Surface upstream and processing failures to the caller.** An index timeout becomes 404 “No active bulletin PDFs”; total download failure returns HTTP 200 with `status: "error"`, which `handleParseLatest` ignores. Distinguish an empty successful index from an upstream failure and make the frontend display total/partial failures. Test empty-index, timeout, upstream HTTP error, all-failed, mixed-result, and all-already-existing cases. Keep backend response semantics and frontend handling aligned.
- [ ] **F08 — Clean up cancelled downloads.** `asyncio.CancelledError` bypasses the downloader's `except Exception`. A mocked stream cancelled after one chunk left an 8,192-byte file. Clean up on cancellation and re-raise it; verify no partial file remains.
- [ ] **F09 — Bound download resources and avoid blocking the event loop.** Download streaming has no total byte cap, and synchronous PDF parsing/database work runs directly inside async routes. Add an enforced download limit and move blocking work to a suitable execution context without sharing a SQLAlchemy session concurrently. Verify oversized-download cleanup and responsiveness during parsing.
- [ ] **F10 — Make concurrency guarantees explicit and enforce them.** The cooldown is process-local. With multiple workers, separate cooldowns allow concurrent scrapes, and query-then-insert persistence has no uniqueness constraint on storm/bulletin identity. Enforce shared scrape coordination and database uniqueness/conflict handling, or explicitly constrain supported deployment to one worker until those guarantees exist. Validate the supported concurrency model.
- [ ] **F11 — Add the missing regression and endpoint coverage.** Cover F01–F10 and the upload traversal, size-limit, and rollback cases. The current regression file's header claims upload-path and rollback coverage, but no tests exercise those routes. Use representative extracted bulletin text/PDF fixtures rather than only the existing happy-path fixture. Record what was tested and any integration checks that remain unavailable.

## Files to resume in

| File | Work |
| --- | --- |
| [bulletin_parser.py](../backend/app/services/bulletin_parser.py) | Link fetching, downloads, metadata/signal parsing, persistence |
| [bulletins.py](../backend/app/api/bulletins.py) | Endpoint errors, cooldown, upload handling, blocking work |
| [models.py](../backend/app/models/models.py) and [init_schema.sql](../backend/init_schema.sql) | Persistence identity constraints; keep model and schema aligned |
| [MonitoringModule.tsx](../frontend/src/app/components/MonitoringModule.tsx) and [api.ts](../frontend/src/lib/api.ts) | Display scrape failures and keep result types aligned |
| [test_bulletin_parser.py](../backend/tests/test_bulletin_parser.py) and [test_bulletin_parser_regression.py](../backend/tests/test_bulletin_parser_regression.py) | Extend regression coverage and add endpoint tests |

## Validation and completion

The existing tests were run from the repository root with the installed backend environment:

```bash
cd backend
venv/bin/python -B -m unittest discover -s tests -p 'test_bulletin*.py' -v
```

Use the equivalent Python interpreter if your virtual environment has a different name.

Before marking this work complete:

1. Resolve each open item above and record the implementation commit and test evidence. Any deferred item keeps the status partial and must state its deployment limitation.
2. Run the existing and added regression/endpoint tests and verify the frontend displays failures.
3. Validate representative PAGASA bulletin fixtures against a test PostGIS database, including persisted signals, source dates, duplicate handling, and rollback. Record live-server verification separately and avoid repeated requests to PAGASA.
4. Obtain a follow-up review, then update this status and the root/backend README summaries together.

The [original review context](../backend/app/services/context.md) is retained for history. This document is the current handoff and completion checklist.
