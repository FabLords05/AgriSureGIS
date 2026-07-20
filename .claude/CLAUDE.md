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
4. Capstone Manuscript ([.claude/Revised AgriSureGIS Manuscript.pdf](.claude/Revised%20AgriSureGIS%20Manuscript.pdf))
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

## Required Process for All Tasks
Before writing any code or making modifications, you must first summarize and present the following:
1. **Your understanding of my task.**
2. **Files likely to be affected.**
3. **Potential dependencies.**
4. **Questions or concerns.**

> [!IMPORTANT]
> **Do not write code yet.** Wait for User's explicit approval before making any changes.
