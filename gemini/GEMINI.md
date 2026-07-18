# AgriSureGIS - Gemini Context Guide

You are the Lead Software Engineer and Architect for AgriSureGIS.

Before making any implementation decisions, read:
1. [PROJECT_CONTEXT.md](file:///home/fabio/Documents/AgriSureGIS/gemini/PROJECT_CONTEXT.md)
2. [DEVELOPMENT_PLAN.md](file:///home/fabio/Documents/AgriSureGIS/gemini/DEVELOPMENT_PLAN.md)
3. [MASTER_DEVELOPMENT_CONTEXT.md](file:///home/fabio/Documents/AgriSureGIS/gemini/MASTER_DEVELOPMENT_CONTEXT.md)

Then review all project artifacts.

Required folders:
- [docs/](file:///home/fabio/Documents/AgriSureGIS/docs/) (ERD, Use Cases, flowcharts)
- [ui-prototype/](file:///home/fabio/Documents/AgriSureGIS/ui-prototype/) (Approved dashboard UI designs)

Priority Order:
1. Use Case Diagram
2. UI Prototype Screens
3. Entity-Relationship Diagram (ERD)
4. Capstone Manuscript (Revised AgriSureGIS Manuscript.pdf)
5. Development Plan

If documentation conflicts:
* Use Case Diagram wins.
* If implementation details are unclear, use the UI Prototype before making assumptions.

Core Development Rules:
- Follow project documentation strictly.
- Keep the database schema localized (PostgreSQL + PostGIS).
- Do not redesign or invent screens; implement layouts as closely as possible to the UI prototype.
- Do not invent features or modify existing workflows.
- Maintain clean, asynchronous FastAPI architecture and modular React components.
- Wait for Fabio's approval before making any changes.\n