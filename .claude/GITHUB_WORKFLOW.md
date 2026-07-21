# AgriSureGIS - Git Workflow

## Branches
- **`main`:** Frozen until final, release-ready code. Protected — never commit directly, never merge into except for a release (see Phase 7).
- **`develop`:** Integration branch. All feature branches merge here first via PR. Represents the current, shared state of development. Also protected — never commit directly.
- **`<username>/<area>/<slug>`:** Individual feature branches, branched off `develop`. `area` is the part of the system you're touching. Examples:
  - `fabio/db/recsap-matrix-table`
  - `cristian/backend/pagasa-scraper`
  - `james/frontend/leaflet-integration`
  - `karylle/docs/api-contract`
  - `albritch/analysis/payout-requirements`

## Phase 1 — Before Coding
1. Update your local `develop`:
   ```bash
   git checkout develop
   git pull origin develop
   ```
2. Create your branch:
   ```bash
   git checkout -b <username>/<area>/<slug>
   ```

## Phase 2 — During Development
- Work only inside your own branch.
- Commit frequently with descriptive messages (`feat:`, `fix:`, `chore:`, `docs:` prefixes). Ensure `.env` is never staged.
- If `develop` moves while you're working, merge the latest changes into your branch:
  ```bash
  git checkout develop
  git pull origin develop
  git checkout <username>/<area>/<slug>
  git merge develop
  ```

## Phase 3 — Before Pushing
Checklist:
- [ ] Project runs locally
- [ ] No secrets or `.env` files committed
- [ ] No unnecessary/generated files committed
- [ ] Code follows `.claude/CLAUDE.md`'s documentation-first rules (Use Case Diagram / ERD / UI Prototype)
- [ ] UI changes match the approved prototype, where applicable

## Phase 4 — Pull Request
Push your branch and open a PR from `<username>/<area>/<slug>` into `develop`.

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
- Merge into `develop` once approved.
- Delete the feature branch after merge — it has served its purpose.

## Phase 7 — Release to `main`
- `main` only moves when the team agrees the current state of `develop` is final, release-ready code (e.g. capstone submission/defense milestone) — not on every feature merge.
- Open a PR from `develop` into `main`. Same review requirement as Phase 5 applies.
- After merging, development continues on `develop`; `main` stays frozen again until the next release point.

## Setup Note (one-time)
- The `develop` branch and GitHub branch protection rules for both `main` and `develop` (block direct pushes, require PR review) must be configured by Fabio in the GitHub repo's Settings → Branches — this isn't something achievable from the local git CLI alone.
