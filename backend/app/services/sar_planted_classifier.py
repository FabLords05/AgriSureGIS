"""
Per-farm `isPlanted` rule -- Phase 2 of docs/SAR_ISPLANTED_METHOD.md §3
(2026-10-12). Pure Python over an already-extracted polygon-mean Sentinel-1
time series, so it is testable without Earth Engine; the series itself comes
from gee_sar_service.fetch_backscatter_series() via the tbl_sar_observation
cache (app/api/sar.py).

Two outcomes only, per Cristian: GREEN ("planted") when every condition
passes, YELLOW ("field_verify") otherwise. SAR never declares a farm "not
planted" on its own -- neither study validates a planted/unplanted cut-off,
so anything short of a clear rice signature goes to field verification.

Evidence base (both PhilGEOS x GeoAdvances 2019, IRRI/PhilRice):
  [A] Gutierrez et al., The Rice Planting Window in the Philippines.
      Rice = "initial deliberate agronomic flooding followed by rapid
      biomass increase"; SoS conditions: VV+VH backscatter, a rise after
      SoS, SoS agreement between VV and VH, incidence angle. SoS vs farmer
      dates: mean deviation 23 days.
  [B] Villano et al., Separability of Transplanted and Direct Seeded Rice.
      Field-mean VH ~-17.5 dB at establishment to ~-15 dB at heading;
      VV/VH ~7.0 -> ~5.2 dB; varieties mature in 100-120 days.

The thresholds below are read from [B]'s boxplots, not published cut-offs,
and are set slightly under [B]'s season swing so a normal crop clears them.
They must be recalibrated locally (method doc §6) before the manuscript
quotes any accuracy.
"""
from dataclasses import dataclass
from datetime import date, timedelta

# Observation window W (method doc §3): long enough to contain the flood
# minimum of a crop still standing at the typhoon (MATURITY_DAYS) plus margin.
OBSERVATION_WINDOW_DAYS = 150

# ~150 days at a 12-day revisit is ~12 scenes; fewer than this and the
# dip-then-rise can't be told from noise.
MIN_OBSERVATIONS = 6

# tp search window after t0 (method doc §3): tillering to heading.
PEAK_SEARCH_START_DAYS = 30
PEAK_SEARCH_END_DAYS = 90

# [B]: Philippine varieties mature in 100-120 days -- past this the crop is
# harvested and nothing is standing to damage.
MATURITY_DAYS = 120

# C2 / C3 thresholds (dB). [B]: VH rises ~2.5 dB, VV/VH drops ~1.8 dB.
RISE_VH_DB = 2.0
DROP_RATIO_DB = 1.5

# C4: [A]'s "correspondence of SoS date in VV and VH". Two 12-day
# acquisitions, matching [A]'s 23-day mean SoS deviation.
VV_VH_MAX_GAP_DAYS = 24

# C5 planting window for Northern Mindanao (Region X), from [A] Table 3 and
# Figs. 6-7: Semester 2 (wet) starts in June and runs ~76 days; Semester 1
# (dry) starts in September and runs ~122 days. Padded each side by [A]'s
# 23-day SoS deviation. (start_month, duration_days).
PLANTING_SEASONS = ((6, 76), (9, 122))
SOS_DEVIATION_DAYS = 23

STATUS_PLANTED = "planted"
STATUS_FIELD_VERIFY = "field_verify"

REASON_PLANTED = "all_conditions_met"
REASON_LABELS = {
    REASON_PLANTED: "All 5 conditions met",
    "no_boundary": "No GPX boundary",
    "too_small": "Too small after 20 m buffer",
    "too_few_scenes": "Too few images / no orbit coverage",
    "no_flood_minimum": "No flooding low point (C1)",
    "crop_too_young": "Flooded under 30 days before typhoon",
    "no_biomass_rise": "No biomass rise (C2)",
    "no_canopy_closure": "No canopy closure (C3)",
    "vv_vh_disagree": "VV and VH disagree on start (C4)",
    "outside_planting_window": "Outside planting window (C5)",
}


@dataclass(frozen=True)
class Observation:
    scene_date: date
    vv_db: float
    vh_db: float

    @property
    def ratio_db(self) -> float:
        # Inputs are dB, so VV - VH is the VV/VH ratio in dB.
        return self.vv_db - self.vh_db


@dataclass
class CheckResult:
    status: str
    reason_code: str
    scene_count: int = 0
    t0_date: date | None = None
    tp_date: date | None = None
    vh_rise_db: float | None = None
    ratio_drop_db: float | None = None


def observation_window(event_date: date) -> tuple[date, date]:
    """Inclusive [start, end]: the 150 days before the typhoon, ending the
    day before its first bulletin (pre-event only, method doc §8)."""
    return event_date - timedelta(days=OBSERVATION_WINDOW_DAYS), event_date - timedelta(days=1)


def in_planting_window(d: date) -> bool:
    """[A]'s Region X planting window, padded by the SoS deviation.
    Semester 1 crosses New Year, so the previous year's seasons are checked too."""
    for year in (d.year - 1, d.year):
        for month, duration in PLANTING_SEASONS:
            season_start = date(year, month, 1)
            if (season_start - timedelta(days=SOS_DEVIATION_DAYS)
                    <= d
                    <= season_start + timedelta(days=duration + SOS_DEVIATION_DAYS)):
                return True
    return False


def _field_verify(reason_code: str, scene_count: int, **metrics) -> CheckResult:
    return CheckResult(status=STATUS_FIELD_VERIFY, reason_code=reason_code, scene_count=scene_count, **metrics)


def classify(observations: list[Observation], event_date: date) -> CheckResult:
    """
    Method doc §3, one farm, one relative orbit:

      t0 = argmin(VH) over W                      flood minimum
      tp = argmax(VH) over [t0 + 30d, t0 + 90d]   biomass peak
      C1 t0 exists and is not at the window edge
      C2 VH[tp] - VH[t0] >= RISE_VH_DB
      C3 ratio[t0] - ratio[tp] >= DROP_RATIO_DB
      C4 argmin(VV) within VV_VH_MAX_GAP_DAYS of t0
      C5 t0 in the Region X planting window and event <= t0 + 120d

    Green only if all pass; the first failure is the reported reason.
    """
    start, end = observation_window(event_date)
    series = sorted(
        (o for o in observations if start <= o.scene_date <= end),
        key=lambda o: o.scene_date,
    )
    n = len(series)
    if n < MIN_OBSERVATIONS:
        return _field_verify("too_few_scenes", n)

    # Ties go to the earliest scene so the result is deterministic.
    t0_index = min(range(n), key=lambda i: (series[i].vh_db, i))
    t0 = series[t0_index]
    if t0_index in (0, n - 1):
        return _field_verify("no_flood_minimum", n, t0_date=t0.scene_date)

    peak_from = t0.scene_date + timedelta(days=PEAK_SEARCH_START_DAYS)
    peak_to = t0.scene_date + timedelta(days=PEAK_SEARCH_END_DAYS)
    candidates = [o for o in series if peak_from <= o.scene_date <= peak_to]
    if not candidates:
        return _field_verify("crop_too_young", n, t0_date=t0.scene_date)
    tp = max(candidates, key=lambda o: (o.vh_db, -o.scene_date.toordinal()))

    metrics = {
        "t0_date": t0.scene_date,
        "tp_date": tp.scene_date,
        "vh_rise_db": round(tp.vh_db - t0.vh_db, 2),
        "ratio_drop_db": round(t0.ratio_db - tp.ratio_db, 2),
    }
    if metrics["vh_rise_db"] < RISE_VH_DB:
        return _field_verify("no_biomass_rise", n, **metrics)
    if metrics["ratio_drop_db"] < DROP_RATIO_DB:
        return _field_verify("no_canopy_closure", n, **metrics)

    vv_min = min(series, key=lambda o: (o.vv_db, o.scene_date))
    if abs((vv_min.scene_date - t0.scene_date).days) > VV_VH_MAX_GAP_DAYS:
        return _field_verify("vv_vh_disagree", n, **metrics)

    if not in_planting_window(t0.scene_date) or event_date > t0.scene_date + timedelta(days=MATURITY_DAYS):
        return _field_verify("outside_planting_window", n, **metrics)

    return CheckResult(status=STATUS_PLANTED, reason_code=REASON_PLANTED, scene_count=n, **metrics)


def pick_orbit_series(rows: list[tuple[int, Observation]]) -> tuple[int | None, list[Observation]]:
    """Method doc §5.1: a farm's series must come from one relative orbit so
    incidence angle stays comparable. Picks the orbit with the most scenes
    for this farm (ties to the lowest orbit number). `rows` is
    (relative_orbit, Observation)."""
    by_orbit: dict[int, list[Observation]] = {}
    for orbit, obs in rows:
        by_orbit.setdefault(orbit, []).append(obs)
    if not by_orbit:
        return None, []
    orbit = min(by_orbit, key=lambda o: (-len(by_orbit[o]), o))
    return orbit, by_orbit[orbit]
