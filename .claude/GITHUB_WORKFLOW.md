# AgriSureGIS - Git Workflow

## Branches
- **`main`:** Production-ready code only. Protected — never commit directly.
- **`<username>/<area>/<slug>`:** Individual feature branches, branched directly off `main`. `area` is the part of the system you're touching. Examples:
  - `fabio/db/recsap-matrix-table`
  - `cristian/backend/pagasa-scraper`
  - `james/frontend/leaflet-integration`
  - `karylle/docs/api-contract`
  - `albritch/analysis/payout-requirements`

There is no `develop` branch in this repo — pull requests target `main` directly.

## Phase 1 — Before Coding
1. Update your local `main`:
   ```bash
   git checkout main
   git pull origin main
   ```
2. Create your branch:
   ```bash
   git checkout -b <username>/<area>/<slug>
   ```

## Phase 2 — During Development
- Work only inside your own branch.
- Commit frequently with descriptive messages (`feat:`, `fix:`, `chore:`, `docs:` prefixes). Ensure `.env` is never staged.
- If `main` moves while you're working, merge the latest changes into your branch:
  ```bash
  git checkout main
  git pull origin main
  git checkout <username>/<area>/<slug>
  git merge main
  ```

## Phase 3 — Before Pushing
Checklist:
- [ ] Project runs locally
- [ ] No secrets or `.env` files committed
- [ ] No unnecessary/generated files committed
- [ ] Code follows `.claude/CLAUDE.md`'s documentation-first rules (Use Case Diagram / ERD / UI Prototype)
- [ ] UI changes match the approved prototype, where applicable

## Phase 4 — Pull Request
Push your branch and open a PR from `<username>/<area>/<slug>` into `main`.

PR template:
```
Title: <short description>

Completed:
- ...

Tested:
- ...

Known issues:
- ...
```

## Phase 5 — Code Review
- Fabio and at least one other developer must review and approve before merging (per `.claude/TEAM_RESPONSIBILITIES.md`).
- Any database structure modifications must be proposed to Fabio specifically.

## Phase 6 — Merge & Cleanup
- Merge into `main` once approved.
- Delete the feature branch after merge — it has served its purpose.
