# SAR `isPlanted` Detection Method

**Status:**
- **Phase 1 (2026-10-12):** the §7 primary VV/VH colour render over the
  affected polygons. It is now an optional overlay. It uses a 24-day
  pre-event median from a single orbit, so it is weaker evidence than §3.
- **Phase 2 (2026-10-12, Cristian):** the §3 rule runs automatically on
  every affected farm. Each farm comes back **GREEN `planted`** (all five
  conditions pass, so no field visit) or **YELLOW `field_verify`**
  (anything else, with the first failed condition as the reason). SAR never
  declares "not planted" on its own. The per-farm Sentinel-1 series is
  cached in `tbl_sar_observation`, so Earth Engine is queried once per farm
  and date range. The manual Planted / Not planted buttons were removed from
  the UI, and yellow farms go to field verification outside the app.
- **Code:** `backend/app/services/sar_planted_classifier.py` (rule),
  `backend/app/services/gee_sar_service.py` (Earth Engine),
  `backend/app/api/sar.py` (`POST /sar/check`, cache),
  `frontend/src/app/components/SarAnalysisPanel.tsx`.
- **Not yet implemented:** the §3.2 percentage, the §7 sparkline, and the §6
  calibration.

Implementation choices for Phase 2:
- **Per typhoon, not per bulletin** (Cristian, 2026-10-12). The AOI is every
  insured farm in a municipality under TCWS signal 2+ in **any** of the
  typhoon's bulletins. It is picked in Spatial Analysis through an
  "Affected by" typhoon dropdown, which replaced the bulletin-scoped
  "Affected Only" toggle.
- **One orbit per farm, not per request** (§5.1). Every descending relative
  orbit is fetched, and each farm uses the orbit with the most scenes over
  it.
- **Farms dropped before Earth Engine is called.** A farm with nothing left
  after the 20 m inward buffer is yellow `too_small` (§5.2). A farm with no
  GPX polygon is yellow `no_boundary`.
- **C4 is implemented as [A]'s SoS agreement.** VV's minimum must fall
  within 24 days (two acquisitions) of VH's `t0`. It is not "VV rises",
  because [B] shows field-mean VV nearly flat (~−10 dB) across the season.
- **C5's Region X window** is [A]'s Northern Mindanao start months (June for
  Semester 2, September for Semester 1) plus their planting durations (76
  and 122 days), padded each side by [A]'s 23-day SoS deviation.
- **A farm whose flood minimum is under 30 days before the typhoon** has no
  biomass-peak scene yet. It is yellow `crop_too_young`, not scored as
  unplanted.
**Purpose:** Defines how AgriSureGIS determines whether an insured farm polygon
carried a standing rice crop at the time of a typhoon, using Sentinel-1 SAR via
Google Earth Engine.
**Requirement served:** FR 3.4 — *"The system shall interface with Google Earth
Engine to retrieve Synthetic Aperture Radar (SAR) imagery to analyze the
percentage of area planted within the polygons."*

---

## 1. Why this exists

A parametric payout is triggered by wind exposure, not by inspection. That
leaves one validation gap: a policy can be in force over a parcel that was
never actually planted for the covered season. The GIS Specialist closes that
gap by looking at SAR imagery for the affected polygons and judging whether a
crop was standing.

This document defines what the system computes to support that judgement. The
final determination stays with the Specialist — the system presents evidence,
it does not auto-approve or auto-reject a claim.

## 2. Evidence base

Two peer-reviewed Philippine studies (PhilGEOS x GeoAdvances 2019, IRRI /
PhilRice) form the basis. Both work on Philippine rice, with Philippine ground
truth, which is why they are preferred over generic C-band literature.

**[A] Gutierrez, M.A., et al. (2019).** *The Rice Planting Window in the
Philippines: An Analysis Using Multi-Temporal SAR Imagery.* Int. Arch.
Photogramm. Remote Sens. Spatial Inf. Sci., XLII-4/W19, 241–248.
https://doi.org/10.5194/isprs-archives-XLII-4-W19-241-2019

**[B] Villano, L., et al. (2019).** *Separability of Transplanted and Direct
Seeded Rice Using Multitemporal Sentinel-1A Data.* Int. Arch. Photogramm.
Remote Sens. Spatial Inf. Sci., XLII-4/W19, 471–478.
https://doi.org/10.5194/isprs-archives-XLII-4-W19-471-2019

### 2.1 What [A] establishes

Rice is detected by a **temporal signature**, not by brightness in a single
image: *"the initial deliberate agronomic flooding followed by rapid biomass
increase."* Their rule-based Start of Season (SoS) detection combines four
conditions:

1. SAR backscatter value (VV **and** VH polarisation)
2. An increase in backscatter observed after the SoS
3. Correspondence of the SoS date between VV and VH
4. Local incidence angle (LIA) in overlapping areas

**Validation:** 93% rice-map accuracy; SoS vs. farmer-reported planting dates
R² = 0.71 (n = 482 ground observations); mean deviation **23 days** (≈ two
acquisitions).

### 2.2 What [B] establishes

Field-mean backscatter across growth stages for 186 fields in four provinces,
wet season 2018. Values below are read from the paper's boxplots (Fig. 3) —
the paper publishes distributions, not a numeric table, so treat these as
**indicative, to be re-derived locally** (see §6).

| Growth stage | VV (dB) | VH (dB) | VV/VH (dB) |
|---|---|---|---|
| Land preparation | ~ −10 | ~ −16.5 | ~ 6.5 |
| Crop establishment | ~ −10 | **~ −17.5** (season min) | ~ 7.0 |
| Tillering–stem elongation | ~ −10 | ~ −16 | ~ 6.5 |
| Heading–flowering | ~ −10 | **~ −15** (season max) | **~ 5.2** (season min) |
| Maturity | ~ −10 | ~ −15 | ~ 5.3 |

Two consequences drive the design:

- **The VH dynamic range is only ~2–3 dB** on field means over the whole
  season. This is far tighter than the 6–10 dB often quoted for C-band
  vegetation generally, and it rules out a simple single-date VH threshold as
  a reliable discriminator.
- **The VV/VH ratio carries the canopy-closure signal.** It drops ~1.8 dB
  from establishment to heading in [B]'s Fig. 3, and a ratio also partially
  cancels incidence-angle and calibration differences between passes.
  (Correction, 2026-10-12: an earlier revision cited [B] Table 4 for this.
  That table's Mann-Whitney U tests compare **transplanted vs. direct-seeded**
  rice at each stage, not one growth stage against another, so it says
  nothing about planted vs. unplanted. [B] sampled no unplanted fields at
  all, which is why no threshold here is a published cut-off.)

## 3. Definition of `isPlanted`

Per farm polygon, over an observation window ending immediately **before** the
typhoon date, build a **polygon-mean** time series of VV and VH in dB.

```
Let W   = observation window = [typhoon_date − 150d, typhoon_date − 1d]
Let t0  = argmin(VH) over W                       # agronomic flooding minimum
Let tp  = argmax(VH) over [t0 + 30d, t0 + 90d]    # biomass peak

C1  Flood minimum found    t0 exists within W, and t0 is not at the window edge
C2  Biomass rise           VH[tp] − VH[t0]            >= RISE_VH_DB     (~2.0)
C3  Canopy closure         (VV/VH)[t0] − (VV/VH)[tp]  >= DROP_RATIO_DB  (~1.5)
C4  Dual-pol agreement     argmin(VV) within 24d of t0                  [A] cond. 3
C5  Timing plausibility    t0 within the Region X planting window (§4)
                           AND typhoon_date ∈ [t0, t0 + 120d]

isPlanted = C1 ∧ C2 ∧ C3 ∧ C4 ∧ C5

GREEN  planted        isPlanted is true -- no field visit
YELLOW field_verify   anything else, with the first failed condition as the reason
```

`120d` in C5 comes from [B]: Philippine varieties have 100–120 day maturity
duration; the three most popular varieties in their sample (NSIC Rc222, NSIC
Rc216, PSB Rc18) run 112–123 days. Past that window the crop is harvested and
there is nothing standing to damage.

All thresholds are **named constants to be calibrated** (§6), never hard-coded
magic numbers.

### 3.1 Relationship to the insurance record

C5 cross-checks the SAR-derived `t0` against `InsuranceRecord.effectivity_date`
and the crop stage already resolved by `backend/app/services/crop_stage_resolver.py`.

**The SAR result must not override the policy record.** [A]'s SoS carries a
mean deviation of 23 days, which is roughly the width of a single growth stage.
SAR corroborates the declared crop stage; it is not accurate enough to replace
it, and the indemnity calculation continues to use the declared stage.

### 3.2 Percentage planted (FR 3.4)

```
area_planted_% = (pixels in polygon satisfying the rule / total pixels) × 100
```

**Caveat that must be carried with the number:** the evidence in §2.2 is
*field-mean* backscatter. At per-pixel level, speckle is comparable to the
~2.5 dB separation the rule depends on, so a per-pixel percentage is noisier
than the polygon-level verdict. The percentage is reported to satisfy FR 3.4,
but it is presented with a confidence flag, and the polygon-mean temporal curve
is the primary evidence shown to the Specialist.

## 4. Region X planting calendar

From [A], used for the C5 plausibility check only — never as a hard gate, since
planting shifts with weather.

| Item | Value |
|---|---|
| Semester 1 (dry) | planted Sep 16 – Mar 15 |
| Semester 2 (wet) | planted Mar 16 – Sep 15 |
| Northern Mindanao, Sem 1 start | September — **among the earliest in the country** |
| Northern Mindanao, Sem 2 start | June — among the latest |
| Northern Mindanao planting duration | Sem 1: 122 days; Sem 2: 76 days |
| Misamis Oriental | named in [A] as an early-peak province (September, Sem 1) |

Misamis Oriental and Bukidnon are both in scope for AgriSureGIS (Claveria and
Talakag are the currently seeded municipalities), so [A]'s provincial results
apply directly rather than by extrapolation.

[A] excluded Mindanao 2016 from its analysis because of drought, and
demonstrated that the planting window shifted materially that year. The window
is therefore advisory: a farm failing C5 on timing alone is flagged for review,
not scored as unplanted.

## 5. Data and preprocessing

| Parameter | Value | Source |
|---|---|---|
| Collection | `COPERNICUS/S1_GRD` | GEE |
| Mode | IW (Interferometric Wide swath) | [A], [B] |
| Product | GRD, high resolution | [A], [B] |
| Polarisation | VV + VH | [A], [B] |
| Pass | Descending, **single relative orbit** per typhoon | [B] §3.1.2 |
| Native resolution | 10 m (GEE) vs. 20 m in [A]/[B] | — |
| Revisit | 12 days per satellite | [A], [B] |

### 5.1 Deviations from the published method

These are real differences, stated plainly rather than glossed:

- **MAPscape-RICE® is proprietary.** Both papers preprocess to terrain-geocoded
  σ° with it, including a temporal smoothing step for anomalously high
  backscatter. GEE's `COPERNICUS/S1_GRD` arrives already calibrated, thermal-
  noise-removed and terrain-corrected, which is close but not identical. The
  temporal smoothing must be reimplemented (a focal/temporal median over the
  series is the pragmatic substitute). Results will not be numerically
  identical to the papers'.
- **Resolution differs** (10 m vs. 20 m). Polygon means are computed over more,
  smaller pixels. This does not invalidate the thresholds but is one more
  reason to recalibrate locally.
- **Satellite constellation.** Both papers assume Sentinel-1A + Sentinel-1B for
  a 6-day revisit. S-1B failed in 2021; the pairing is now S-1A + S-1C.
  Effective revisit over Region X must be verified before relying on 6-day
  cadence. At 12 days, the flooding minimum `t0` can be missed by up to 11
  days — [A] names this as a limitation.
- **Incidence angle.** [A] includes LIA as an explicit condition; [B] lists not
  analysing it as a limitation. Holding to one relative orbit (§5) is what
  makes the thresholds comparable across dates, and is mandatory.

### 5.2 Polygon handling

[B] excluded portions of sample fields within 60 m of paved roads and removed
boundary pixels before computing field means, to avoid contamination from
bunds, adjacent fields and other land cover. Their samples were 0.4–7 ha,
comparable to PCIC farm sizes.

Accordingly:

- Apply an inward buffer (~20 m) to each farm polygon before sampling.
- A farm too small to survive the buffer is flagged **low confidence** and
  surfaced as such — never silently scored.
- GPX-surveyed boundaries only. A farm with no `location_geom` has no polygon
  to sample and is excluded.

### 5.3 Establishment method caveat

[B]'s central finding is that transplanted (TP) and wet direct seeded (WDS)
rice differ significantly in backscatter during early growth (VV, p < 0.001 at
crop establishment). TP remains the dominant practice in most of the country,
but a threshold calibrated purely on TP fields will misfire on DS fields. This
is a known source of error, to be noted in validation rather than engineered
away at this stage.

## 6. Threshold calibration

No threshold in §3 may ship as a literature value. The required procedure:

1. Select ~20 polygons known to have been planted and ~20 known fallow for the
   same season, from PCIC records or Specialist knowledge.
2. Extract their VH and VV/VH time series over the same window and orbit.
3. Plot the distributions of the C2 rise and C3 drop for both groups.
4. Set `RISE_VH_DB` and `DROP_RATIO_DB` where the two groups separate.
5. Record the resulting separation and any overlap in the manuscript as the
   method's measured performance.

This produces a defensible, locally-derived number rather than a borrowed one,
and gives the capstone a validation result of its own.

## 7. Visual representation

The Specialist's judgement is made on colour. Two renders, both clipped to the
affected polygons only:

**Primary — VV/VH ratio**, stretched to the range actually observed in [B]
rather than an arbitrary one:

```
  4.5 dB ──────── 5.5 ──────── 6.5 ──────── 7.5+ dB
  deep green      green        tan          brown
  canopy closed   planted      sparse       bare / flooded
```

Low ratio = closed canopy = planted. Green reads as planted without requiring
SAR training.

**Secondary — VH time-series sparkline** per polygon, showing the
dip-then-rise. This is the actual evidence the method rests on; a single
frame's colour alone is weaker than what either paper validates, so the curve
is shown alongside, not instead.

## 8. Scope boundaries

- SAR is requested **only for polygons already filtered as affected** by the
  typhoon, never region-wide. This bounds Google Earth Engine compute
  consumption, per FR 2.4 (EEC capacity allocation).
- The pre-event scene requirement in §3 is not optional. A post-event image
  conflates "never planted" with "flattened by the storm" — both can depress
  VH — which would invert the meaning of the check.
- No automated approve/reject. The system computes, renders and flags. Green
  only spares a field visit; yellow sends the farm to field verification. SAR
  alone never rules a farm unplanted.
- `isPlanted` does not feed the indemnity formula. `I = (AC / 1000) * IF`
  is unchanged.

## 9. Open items

- [ ] Verify current Sentinel-1 revisit over Region X (§5.1).
- [x] ~~Select the relative orbit covering Claveria and Talakag.~~ Done per
      farm automatically in Phase 2: each farm uses its best-covered orbit.
- [ ] Run the calibration in §6 and record measured thresholds.
- [ ] Confirm GEE service account `agrisure-ee@webgis-pcic.iam.gserviceaccount.com`
      quota against expected per-typhoon polygon counts.
