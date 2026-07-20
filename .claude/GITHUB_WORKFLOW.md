# AgriSureGIS - Git Workflow

## Branches
- **`main`:** Production-ready code only.
- **`develop`:** Stable development branch.
- **`feature/*`:** Individual feature branches. Examples:
  - `feature/db-setup`
  - `feature/pagasa-parser`
  - `feature/payout-calculator`

## Process
1. **Prepare:** Update your local `develop` branch before coding:
   ```bash
   git checkout develop
   git pull origin develop
   ```
2. **Branch:** Create a dedicated branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Commit:** Make frequent, descriptive commits. Ensure `.env` is never staged.
4. **Merge:** Pull latest changes from `develop` into your branch frequently to resolve conflicts:
   ```bash
   git checkout develop
   git pull origin develop
   git checkout feature/your-feature-name
   git merge develop
   ```
5. **Review:** Push to GitHub and create a Pull Request from `feature/your-feature-name` to `develop`. Fabio and the team will review the code before merging.\n