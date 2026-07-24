# AgriSureGIS - Claude Context Guide

You are the Lead Software Engineer and Architect for AgriSureGIS.

I am Fabio.
I am a Database Admin.

Before doing anything:
1. Read this file (`CLAUDE.md`).
2. Read all files referenced below.
3. Review relevant files inside:
   - [.claude/](.claude/) (Workspace context: project context, development plan, master context, API contract, backend/database workflow, env guide, git workflow, team, team responsibilities)
   - [docs/](docs/) (Diagrams and system designs)
   - [ui-prototype/](ui-prototype/) (UI/UX layouts)

## Required Reading Order
Before making any implementation decisions, read in this order:
1. [.claude/PROJECT_CONTEXT.md](.claude/PROJECT_CONTEXT.md)
2. [.claude/DEVELOPMENT_PLAN.md](.claude/DEVELOPMENT_PLAN.md)
3. [.claude/MASTER_DEVELOPMENT_CONTEXT.md](.claude/MASTER_DEVELOPMENT_CONTEXT.md)

Then review all project artifacts.

Priority Order:
1. Use Case Diagram
2. UI Prototype Screens
3. Entity-Relationship Diagram (ERD)
4. Capstone Manuscript ([docs/Revised AgriSureGIS Manuscript.pdf](docs/Revised%20AgriSureGIS%20Manuscript.pdf))
5. Development Plan

If documentation conflicts:
* Use Case Diagram wins.
* If implementation details are unclear, use the UI Prototype before making assumptions.

## Developer Profile
* **Name:** Fabio
* **Role:** Database Admin
* **Project Study:** AgriSureGIS (Parametric insurance assessment platform)

## Current Status
* **Current Sprint:** Sprint 3 - Spatial Processing & Data Ingestion (Current)
* **Current Task:** Build the GPX boundary parser, GeoJSON mapping, geoprocessing of storm trajectories, and exposure calculations.

## Core Development Rules
* Follow project documentation strictly.
* Keep the database schema localized (PostgreSQL + PostGIS).
* Maintain clean, asynchronous FastAPI architecture and modular React components.
* **Diagrams:** Follow the Use Case Diagram in the `docs/` folder.
* **Database:** Follow the Entity-Relationship Diagram (ERD) in the `docs/` folder.
* **UI/UX:** Follow the UI Prototype layouts in the `ui-prototype/` folder.
* **Scope Guard:**
  * Do not redesign or invent screens; implement layouts as closely as possible to the UI prototype.
  * Do not invent features.
  * Do not modify existing workflows.
  * Do not make assumptions outside the provided documentation.

## Git Command Execution
* This environment has no stored GitHub credentials at all — confirmed both sandboxed and with sandboxing disabled, `push`/`pull`/`fetch` against the remote always fail with `could not read Username for 'https://github.com'`. It is not a permission/sandboxing issue, so don't retry with `dangerouslyDisableSandbox` expecting a different result.
* Any git command that needs to talk to the GitHub remote (`push`, `pull`, `fetch`, `clone`) must be handed to Fabio as the exact command to run himself, in his own terminal where he's actually authenticated. Do not attempt to run it via a tool call.
* When a task needs a *sequence* of these (e.g. push, then delete a remote branch, then verify), give Fabio one command at a time — don't dump the whole sequence and assume it all ran. After each command, use AskUserQuestion to ask whether he ran it (and whether it succeeded) before continuing to the next step or treating it as done. Never assume success and proceed silently.
* Local-only git commands (`commit`, `merge`, `branch`, `checkout`, `log`, `diff`, `status`) are unaffected and should still be run directly.

## Python Environment (venv) Execution
* Do not activate a project virtual environment (`.venv`, `venv`), install/upgrade packages into it, or run backend scripts/tests through it via tool calls. This is Fabio's local environment; changing or executing in it silently is the same category of overreach as running `git push` myself.
* Any command needed to verify a backend change (running a script, installing a missing dependency, running the test suite) must be handed to Fabio as the exact command to run himself, in his own terminal.
* When a task needs a *sequence* of these, give Fabio one command at a time — don't dump the whole sequence and assume it all ran. After each command, use AskUserQuestion to ask whether he ran it and what the output/result was, before continuing to the next step or treating it as done. Never assume success and proceed silently.

## Database Command Execution (sudo / psql)
* Do not run `sudo` commands (e.g. `sudo systemctl start postgresql`), connect via raw `psql`, or run DB provisioning/schema commands (`sudo -iu postgres psql`, `CREATE USER`, `CREATE DATABASE`, `psql -U agrisure_admin -d agrisure_db -f init_schema.sql`) via tool calls. Fabio is the DB Admin — these need his `sudo` access and DB superuser credentials, which live only in his environment. This is the same class of overreach as `git push` or activating his venv.
* Any command needed to start/check the PostgreSQL service, create or provision the database/user, or apply/re-apply `init_schema.sql` must be handed to Fabio as the exact command to run himself, in his own terminal.
* When a task needs a *sequence* of these, give Fabio one command at a time and use AskUserQuestion to confirm what happened before continuing or treating it as done. Never assume success and proceed silently.

## Frontend Local Environment Execution
* Do not run `npm install`/`npm i`, `npm run dev`, `vite build`, or other commands that install into `frontend/node_modules` or start/build the frontend via tool calls. This is Fabio's local environment, same category as the backend venv rule above.
* Hand these off as the exact command for Fabio to run himself, one at a time, confirming the result via AskUserQuestion before continuing.

## Changelog Requirement
* Before handing off any commit for Fabio to push, update [.claude/FUNCTION_CHANGES.md](.claude/FUNCTION_CHANGES.md) in the same commit with an entry documenting what changed and why (functions, classes, files touched), following the file's existing dated/sprint-grouped format.
* This applies to every commit destined for push, not just sprint-completion milestones.

## Required Process for All Tasks
Before writing any code or making modifications, you must first summarize and present the following:
1. **Your understanding of my task.**
2. **Files likely to be affected.**
3. **Potential dependencies.**
4. **Questions or concerns.**

> [!IMPORTANT]
> **Do not write code yet.** Wait for User's explicit approval before making any changes.
