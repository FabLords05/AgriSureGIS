"""
Display formatting for a farmer's name, shared by every endpoint that renders one.

Why this is centralized rather than inlined per endpoint: four call sites
(app/api/farms.py's list_farms + search_farmers, app/api/insurance.py's usage
listing, app/api/assessments.py's CSV export) each built the name with their own
f-string, and all four degraded badly when the underlying name fields were blank
rather than absent -- producing "", ", " and ", ." respectively instead of a
null the UI could fall back on.

That mattered because blank is a state these columns really reach:
tbl_farmers_profile.last_name/first_name are NOT NULL, so CSV ingestion stored ''
for a layout whose name columns the parser didn't recognize yet, which is how 952
nameless farmers landed in the database before the 'FARMER NAME' alias existed
(2026-10-09). The frontend's `farmer_name ?? "—"` can't catch '' -- only null --
so those rows rendered as visually empty cells in Spatial Analysis rather than as
an obvious "no name on file".

Every function here returns None (never '') when nothing usable is on file, so a
missing name is always representable as JSON null and the existing frontend
fallbacks work unchanged.
"""
from typing import Any


def _part(farmer: Any, attribute: str) -> str:
    """One name component, trimmed, or '' if absent/blank. Tolerates both an ORM
    FarmerProfile and the lightweight Row that search_farmers() selects (which
    carries only first_name/last_name), hence getattr rather than attribute access.
    """
    value = getattr(farmer, attribute, None)
    return value.strip() if isinstance(value, str) else ""


def format_given_first(farmer: Any) -> str | None:
    """'ALFONSO ABANES' -- the form the Farm Records table and map popup use.
    None if neither part is on file.
    """
    if farmer is None:
        return None
    full = f"{_part(farmer, 'first_name')} {_part(farmer, 'last_name')}".strip()
    return full or None


def format_surname_first(farmer: Any, *, with_middle_initial: bool = False) -> str | None:
    """'ABANES, ALFONSO' -- the form the insurance usage listing and the payout CSV
    export use. None if neither part is on file.

    with_middle_initial reproduces the payout export's existing shape exactly,
    including its trailing period after the first name ('ABANES, ALFONSO. F.') --
    that quirk predates this helper and is left alone deliberately, since the
    export's column format is PCIC-facing and not ours to change here.

    A blank surname or first name no longer leaves its separator behind: the
    result is whichever part is actually on file, never ', ' or ', .'.
    """
    if farmer is None:
        return None

    last = _part(farmer, "last_name")
    first = _part(farmer, "first_name")
    if not last and not first:
        return None

    if with_middle_initial:
        middle = _part(farmer, "middle_name")
        suffix = f" {middle[0]}." if middle else ""
        if not first:
            return f"{last}{suffix}"
        if not last:
            return f"{first}.{suffix}"
        return f"{last}, {first}.{suffix}"

    if not first:
        return last
    if not last:
        return first
    return f"{last}, {first}"
