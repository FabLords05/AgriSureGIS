# SAR Planted Check — Phase 1 vs Phase 2, and Why Not NDVI

**For:** the system documenter / analyst.
**Written:** 2026-10-18, from a working session between Fabio and Claude Code.
**Status:** explainer. The normative spec is
[`SAR_ISPLANTED_METHOD.md`](SAR_ISPLANTED_METHOD.md) — where the two disagree,
that file wins. Section numbers below (§3, §7, …) refer to it.

This document exists because the SAR feature was built in two passes that look
similar from the outside and are completely different underneath. Anyone
writing about the system will otherwise describe the wrong one, or describe
NDVI, which was never built.

---

## 1. What the feature is for

A parametric payout is triggered by wind exposure, not by inspection. That
leaves one gap: a policy can be in force over a parcel that was never actually
planted for the covered season. The SAR check closes that gap by asking, from
satellite imagery, whether a standing rice crop was there when the typhoon hit.

It serves **FR 3.4** — *"the system shall interface with Google Earth Engine to
retrieve Synthetic Aperture Radar (SAR) imagery to analyze the percentage of
area planted within the polygons"* — and implements **Verify Farm Planted** in
the Use Case Diagram.

Two points to carry into any write-up, because they are easy to get wrong:

1. **The SAR result never affects the money.** `AssessmentService` and the
   PABS/PCIC export do not read it. The indemnity formula `I = (AC / 1000) * IF`
   is untouched by it.
2. **The system never auto-rejects a claim.** It presents evidence and flags
   farms. A green result only spares a field visit.

---

## 2. The two phases at a glance

Both shipped 2026-10-12. Phase 1 draws a picture for a person to judge. Phase 2
decides per farm and produces a work list.

| | **Phase 1** — visual layer | **Phase 2** — automatic check |
|---|---|---|
| Spec section | §7 (colour render) | §3 (the five-condition rule) |
| Endpoint | `POST /api/sar/layer` | `POST /api/sar/check`, `GET /api/sar/checks` |
| Window before the typhoon | **24 days** | **150 days** |
| What is computed | One composite image: `VV − VH` in dB | A **time series** of VH and of the VV/VH ratio |
| Minimum scenes | whatever the window holds | 6 |
| Orbit choice | one orbit for **all** farms | the best-covered orbit **per farm** |
| Who decides planted | the GIS Specialist, by eye | the rule |
| Result values | `planted` / `not planted` / unchecked | `planted` (green) / `field_verify` (yellow) |
| Stored in | `tbl_planted_verification` | `tbl_sar_observation`, `tbl_sar_fetch_coverage`, `tbl_sar_planted_check` |
| Farms considered | all affected farms | affected **and insured when the typhoon hit** |
| Current standing | optional overlay | the live path |

### 2.1 Phase 1 in words

Pull every descending Sentinel-1 scene over the affected farms from the 24 days
before the typhoon's first bulletin. Take a median through them to suppress
speckle, compute `VV − VH` in decibels, clip it to the farm polygons (shrunk
20 m inward so field edges and bunds don't contaminate the value), and colour
the result on a fixed 4.5–7.5 dB scale: deep green → green → tan → brown.

A low ratio means a closed canopy, which reads as green. The Specialist looks
at the map and records **Planted** or **Not planted** per farm by hand.

Caps and caching: at most 5,000 farms per request, tile URL cached one hour.

### 2.2 Phase 2 in words

For each farm, build a 150-day history of polygon-average backscatter ending
the day before the typhoon, then look for the shape that rice makes:

- `t0` — the lowest VH value in the window. This is the **deliberate flooding**
  of the paddy before planting.
- `tp` — the highest VH value between 30 and 90 days after `t0`. This is the
  **biomass peak** as the crop grows.

Five conditions must all hold:

| | Condition | Threshold |
|---|---|---|
| C1 | A flood minimum `t0` exists, not at the window's edge | — |
| C2 | VH rises from `t0` to `tp` | ≥ 2.0 dB |
| C3 | The VV/VH ratio drops from `t0` to `tp` (canopy closing) | ≥ 1.5 dB |
| C4 | VV's own minimum agrees with VH's `t0` | within 24 days |
| C5 | `t0` falls in the Region X planting window, and the typhoon falls within 120 days after `t0` | — |

All five pass → **GREEN `planted`**, no field visit. Anything else → **YELLOW
`field_verify`**, tagged with the first condition that failed.

**The system never returns "not planted."** SAR evidence is not strong enough
to make that call alone, so a failure means *go look*, not *reject*. Yellow
farms are exported to a field-verification list
(`GET /api/sar/field-verify/export`) and handled outside the app.

Reason codes a yellow farm can carry: `no_boundary`, `too_small`,
`too_few_scenes`, `no_flood_minimum` (C1), `crop_too_young`, `no_biomass_rise`
(C2), `no_canopy_closure` (C3), `vv_vh_disagree` (C4),
`outside_planting_window` (C5). Green carries `all_conditions_met`.

---

## 3. Why Phase 2 replaced Phase 1 as the live path

Four reasons, each a real defect in Phase 1 rather than a preference:

1. **A 24-day median cannot show a temporal signature.** The published method
   detects rice by *"the initial deliberate agronomic flooding followed by
   rapid biomass increase"* — a sequence over months. Collapsing 24 days into
   one image throws that away and leaves a single-frame colour, which is weaker
   evidence than the research it cites.
2. **One orbit for all farms left silent gaps.** Farms outside that orbit's
   footprint received no colour at all — indistinguishable, on screen, from
   farms that were checked and found bare. Per-farm orbit selection removes it.
3. **Earth Engine cost.** Phase 2 only checks farms that were insured when the
   typhoon hit, keeping Earth Engine away from the 100,000+ farms with no
   usable cover, and caches every scene value it fetches. A re-run of an
   already-cached typhoon works even with Earth Engine switched off.
4. **Operator load.** Phase 1 asked the Specialist to eyeball every polygon.
   Phase 2 returns a reason-coded triage list.

Phase 1 was not deleted. The colour layer remains available as an optional
overlay, which is genuinely useful for looking at a farm Phase 2 flagged. Its
manual Planted/Not-planted endpoints (`/api/sar/verifications`) also still
exist server-side so verdicts already recorded stay readable, but the frontend
no longer calls them — treat that path as retired, not current.

---

## 4. What both phases share

Worth stating once, since it applies to any description of either:

- Sentinel-1 `COPERNICUS/S1_GRD`, IW mode, VV + VH polarisation, descending
  passes.
- A 20 m inward buffer on every farm polygon before sampling.
- **Pre-event imagery only.** This is not an optimisation; it is correctness.
  A post-event image conflates "never planted" with "flattened by the storm" —
  both depress VH — which would invert the meaning of the check.
- GPX-surveyed boundaries only. A farm with no polygon cannot be sampled.
- Only farms already filtered as affected by the typhoon, never region-wide,
  which bounds Earth Engine consumption per FR 2.4.

---

## 5. Why not NDVI

NDVI appears in the UI prototype (`ui-prototype/src/app/components/AOISARPanel.tsx`
— an "Avg. NDVI" tile, an NDVI column, a "Crop Health Index (NDVI/EVI)"
dropdown) and it is **mock data, in a prototype screen, that was never built.**
There is no NDVI anywhere in `backend/` or `frontend/`. Phase 1's changelog
entry states the exclusion explicitly: *"Planted area only (no flood extent, no
NDVI)."*

Anyone documenting the system from the prototype alone will get this wrong, so
the reasoning is recorded here.

First, a category correction: **NDVI is not a SAR product.** SAR is radar.
NDVI is optical — `(NIR − Red) / (NIR + Red)`, from Sentinel-**2**. Different
satellite, different physics.

| | VV/VH — Sentinel-1 radar | NDVI — Sentinel-2 optical |
|---|---|---|
| Clouds | Sees through them, day or night | Blocked by them |
| Measures | Surface structure and water content | Chlorophyll greenness |
| Flooded paddy | **Detects it** — the basis of the method | Reads it the same as bare soil |
| Useful range | Narrow (~2–3 dB on VH field means) | Wide (~0.05 bare → ~0.8 dense canopy) |
| Revisit | 12 days per satellite | 5 days, cloud-free ones only |
| PH rice validation | Two Philippine studies, 93% map accuracy, 482 ground observations | Not the basis of either |

Two decisive reasons:

1. **Clouds, at exactly the wrong moment.** The method needs imagery from the
   window immediately *before* landfall — peak wet season with a storm
   approaching. The chance of a cloud-free Sentinel-2 scene over Claveria or
   Talakag in that window is poor, and poorest for the farms that matter most.
   NDVI would go blank on the claims being assessed.
2. **NDVI cannot see half the signature.** The rule does not detect *green*; it
   detects flooding followed by biomass growth. Standing water and bare soil
   both read low in NDVI, so C1, C3 and C4 could not be implemented with it
   even under clear skies.

On top of that, FR 3.4 names SAR specifically, so an NDVI path would be a new
feature rather than an implementation detail.

**Where NDVI could legitimately fit later:** as optional corroboration on a
yellow `field_verify` farm, when a cloud-free pre-event scene happens to exist,
before sending someone to the field. That would be a new phase with its own
collection (`COPERNICUS/S2_SR_HARMONIZED`), cloud masking and spec section —
not a substitute for the radar check. It is not planned.

The prototype's "flooded %" was dropped for a related reason: it is a
post-event measurement, which §8 rules out.

---

## 6. Known gaps — do not document these as finished

Accurate as of 2026-10-18, and all tracked in §9 of the method doc:

- **The percentage-planted figure is not implemented.** §3.2 defines it, and it
  is the part FR 3.4 literally asks for. What exists today is a per-farm
  green/yellow verdict, not a percentage. If a requirements document claims
  FR 3.4 is complete, that claim is ahead of the code.
- **The thresholds are literature values, not calibrated ones.** §6 states that
  no threshold may ship as a borrowed number, yet `RISE_VH_DB = 2.0` and
  `DROP_RATIO_DB = 1.5` are still the indicative figures read off the papers'
  boxplots. The calibration procedure in §6 (≈20 known-planted and ≈20 known-
  fallow polygons) has not been run. This is the method's largest open risk and
  the obvious place for a measured validation result.
- **The VH sparkline (§7) is not implemented.** The temporal curve is the actual
  evidence the method rests on, and the UI does not yet show it.
- **Sentinel-1 revisit is unverified.** Both papers assume Sentinel-1A + 1B for
  a 6-day revisit. S-1B failed in 2021; the pairing is now S-1A + S-1C. At
  12 days, the flooding minimum `t0` can be missed by up to 11 days.
- **`tbl_planted_verification` is not in the ERD** (`docs/ERD.drawio.png`).
- The Phase 2 check is synchronous; a first run on a large typhoon can take
  minutes.

---

## 7. Where to verify any of this

| Subject | File |
|---|---|
| The normative method | [`SAR_ISPLANTED_METHOD.md`](SAR_ISPLANTED_METHOD.md) |
| Endpoints, payloads, errors | `.claude/API_CONTRACT.md` §4c |
| What changed and when | `.claude/FUNCTION_CHANGES.md` (2026-10-12 and 2026-10-13 entries) |
| The five-condition rule | `backend/app/services/sar_planted_classifier.py` |
| Earth Engine access | `backend/app/services/gee_sar_service.py` |
| Routes and caching | `backend/app/api/sar.py` |
| The UI | `frontend/src/app/components/SarAnalysisPanel.tsx` |
| Thresholds and constants | top of `sar_planted_classifier.py` |

The two papers the method rests on, cited in full with DOIs in §2 of the
method doc (PDF copies sit in `docs/` on the developers' machines but are not
tracked in the repository):

- **[A]** Gutierrez, M.A., et al. (2019). *The Rice Planting Window in the
  Philippines: An Analysis Using Multi-Temporal SAR Imagery.* — the Start of
  Season rule and the Region X planting calendar.
- **[B]** Villano, L., et al. (2019). *Separability of Transplanted and Direct
  Seeded Rice Using Multitemporal Sentinel-1A Data.* — the per-growth-stage
  backscatter values the thresholds derive from.

---

## 8. Also settled in the same session

Recorded here only as a pointer, so this file does not become a second source
of truth: the team roles were restructured on 2026-10-18 — two core developers
with equal ownership of the whole system (Fabio: database and backend;
Cristian: backend logic and frontend), with frontend design and documentation
as supporting roles. The authority is `.claude/CLAUDE.md`'s "Team at a Glance",
expanded in `.claude/TEAM.md` and `.claude/TEAM_RESPONSIBILITIES.md`. Read
those rather than this paragraph.
