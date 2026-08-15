import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from sqlalchemy.orm import Query as SAQuery

from app.api.farms import list_farms
from app.models.models import Farm, InsuranceRecord


class _ChainableQuery:
    """Minimal stand-in for a SQLAlchemy Query, supporting exactly the chain
    list_farms() uses (.options/.order_by/.filter/.limit -- no .offset(),
    since pagination is keyset/after_id-based, not OFFSET/LIMIT; see
    app/api/farms.py's docstring), where every non-terminal method returns
    self and .all()/.count() return whatever the test configured -- close
    enough to assert both the SQL shape (was .limit() applied? was .filter()
    called, and with what?) and the number of real query executions, without
    needing a live database."""

    def __init__(self, all_result=None, count_result=0):
        self.filter_calls: list = []
        self.order_by_calls: list = []
        self.limit_arg = None
        self.all_call_count = 0
        self.count_call_count = 0
        self._all_result = all_result if all_result is not None else []
        self._count_result = count_result

    def options(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        self.order_by_calls.append(a)
        return self

    def filter(self, *criteria):
        self.filter_calls.extend(criteria)
        return self

    def limit(self, n):
        self.limit_arg = n
        return self

    def all(self):
        self.all_call_count += 1
        return self._all_result

    def count(self):
        self.count_call_count += 1
        return self._count_result


def _in_clause_values(criterion):
    # Mirrors the same SQLAlchemy-internals approach test_upload_csv_ingestion.py
    # already uses: for `Column.in_([...])`, .right.value holds the bound list
    # and .operator identifies it as an IN clause.
    assert getattr(criterion.operator, "__name__", "") == "in_op"
    return list(criterion.right.value)


def _fake_farm(farm_id, municipality="Talakag", province="Bukidnon", barangay="San Isidro"):
    farmer = SimpleNamespace(first_name="Juan", last_name="Dela Cruz")
    boundary = SimpleNamespace(province=province, municipality=municipality, barangay=barangay)
    return SimpleNamespace(
        farm_id=farm_id,
        farmer_id=1,
        farmer=farmer,
        boundary=boundary,
        area_size=1.5,
        csv_farm_reference=f"REF{farm_id}",
        georef_id=None,
        location_geom=None,
    )


def _fake_insurance(farm_id, policy_no="POL-1", effectivity_date=None, expiry_date=None):
    return SimpleNamespace(
        farm_id=farm_id,
        policy_no=policy_no,
        effectivity_date=effectivity_date,
        expiry_date=expiry_date,
    )


def _build_mock_db(farms_all_result=None, farms_count_result=0, insurance_all_result=None):
    """Returns (mock_db, farms_chain, insurance_chain). db.query() is routed
    by which model/column was queried, mirroring list_farms()'s possible
    db.query(...) call sites:
    - Farm and InsuranceRecord (the full entity) get our fake chain, since
      production code calls .all()/.count() on those and we want to control
      the result without a live database.
    - InsuranceRecord.farm_id (a bare column, used only to build the
      active-only subquery via .scalar_subquery()) gets a *real*, unbound
      (`session=None`) SQLAlchemy Query -- list_farms() never executes it
      directly (it's embedded as a correlated subquery inside the outer
      farms query's WHERE clause), so it only needs to support real
      .filter()/.distinct()/.scalar_subquery() SQL-building, not our fake
      .all()/.count(). Farm.farm_id.in_(...) requires a genuine ScalarSelect
      as its operand -- passing it the fake chain raises a real
      sqlalchemy.exc.ArgumentError, so this must be a real construct.

    mock_db.execute is pinned to raise: list_farms() checks
    materialized_view_available(db) (app/core/farms_view.py) before falling
    back to the bulk InsuranceRecord query these tests assert against. A
    bare, unconfigured MagicMock().execute(...).first() returns a truthy
    MagicMock (not None), which would make that check wrongly report the
    view as available -- and since a positive result there is memoized
    process-wide, one test taking that wrong branch would corrupt every test
    that runs after it in the same pytest session. Raising forces the
    deterministic "view not available" fallback path instead, every time.
    """
    farms_chain = _ChainableQuery(all_result=farms_all_result, count_result=farms_count_result)
    insurance_chain = _ChainableQuery(all_result=insurance_all_result)

    def query_side_effect(entity, *rest):
        if entity is Farm:
            return farms_chain
        if entity is InsuranceRecord:
            return insurance_chain
        return SAQuery(entity, session=None)

    mock_db = MagicMock()
    mock_db.query.side_effect = query_side_effect
    mock_db.execute.side_effect = Exception("no materialized view in tests -- forces the fallback path")
    return mock_db, farms_chain, insurance_chain


class ListFarmsUnpaginatedTests(unittest.TestCase):
    def test_no_limit_returns_all_rows_with_no_after_id_limit_calls(self):
        farms = [_fake_farm(1), _fake_farm(2), _fake_farm(3)]
        mock_db, farms_chain, insurance_chain = _build_mock_db(farms_all_result=farms)

        result = list_farms(db=mock_db, limit=None, after_id=0, active_only=False)

        self.assertEqual(len(result["data"]), 3)
        self.assertIsNone(farms_chain.limit_arg)
        # Backward-compat guard for MonitoringModule.tsx's unpaginated call:
        # omitting `limit` must not add the extra COUNT query, nor the
        # after_id > 0 filter (after_id defaults to 0, i.e. "no cursor yet").
        self.assertEqual(farms_chain.count_call_count, 0)
        self.assertEqual(farms_chain.filter_calls, [])
        self.assertEqual(result["total"], 3)
        self.assertIsNone(result["limit"])
        self.assertEqual(result["after_id"], 0)
        self.assertFalse(result["has_more"])

    def test_no_limit_does_not_apply_active_only_filter_by_default(self):
        farms = [_fake_farm(1)]
        mock_db, farms_chain, _ = _build_mock_db(farms_all_result=farms)

        list_farms(db=mock_db, limit=None, after_id=0, active_only=False)

        self.assertEqual(farms_chain.filter_calls, [])


class ListFarmsPaginationTests(unittest.TestCase):
    def test_limit_and_after_id_are_applied_and_total_is_queried(self):
        page = [_fake_farm(1), _fake_farm(2)]
        mock_db, farms_chain, _ = _build_mock_db(farms_all_result=page, farms_count_result=5)

        result = list_farms(db=mock_db, limit=2, after_id=0, active_only=False)

        self.assertEqual(farms_chain.limit_arg, 2)
        # First page (after_id == 0) is the only one that triggers the COUNT.
        self.assertEqual(farms_chain.count_call_count, 1)
        self.assertEqual(result["total"], 5)
        self.assertEqual(result["limit"], 2)
        self.assertEqual(result["after_id"], 0)
        self.assertTrue(result["has_more"])  # a full page (2) came back

    def test_has_more_false_on_last_page(self):
        # Continuing a walk past farm_id 4 (after_id=4); only 1 farm left,
        # short of a full page -- has_more is derived from "did a full page
        # come back", not offset+total arithmetic (there's no offset under
        # keyset pagination).
        page = [_fake_farm(5)]
        mock_db, farms_chain, _ = _build_mock_db(farms_all_result=page, farms_count_result=5)

        result = list_farms(db=mock_db, limit=2, after_id=4, active_only=False)

        self.assertFalse(result["has_more"])  # 1 row came back, short of limit=2
        # after_id > 0 means no COUNT this page (only the first page counts).
        self.assertEqual(farms_chain.count_call_count, 0)
        # ...and the keyset filter (Farm.farm_id > 4) was applied instead.
        self.assertEqual(len(farms_chain.filter_calls), 1)
        criterion = farms_chain.filter_calls[0]
        compiled = str(criterion.compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("farm_id", compiled)
        self.assertIn("> 4", compiled)

    def test_exactly_2_query_executions_per_paginated_request(self):
        mock_db, farms_chain, insurance_chain = _build_mock_db(
            farms_all_result=[_fake_farm(1)], farms_count_result=1
        )

        list_farms(db=mock_db, limit=100, after_id=0, active_only=False)

        # 1 farms SELECT (.all()) + 1 insurance SELECT (.all()) -- the
        # docstring's "2 queries per page" guarantee -- plus the 1 extra
        # COUNT this endpoint now runs only on the first page (after_id == 0).
        self.assertEqual(farms_chain.all_call_count, 1)
        self.assertEqual(insurance_chain.all_call_count, 1)
        self.assertEqual(farms_chain.count_call_count, 1)

    def test_insurance_query_scoped_to_current_page_farm_ids_only(self):
        # Page contains farms 10 and 20; a farm from a different, unfetched
        # page (e.g. 999) must never appear in the insurance IN-clause --
        # regression guard for the bulk insurance fetch staying page-scoped
        # instead of reverting to a whole-table fetch.
        page = [_fake_farm(10), _fake_farm(20)]
        mock_db, _, insurance_chain = _build_mock_db(farms_all_result=page)

        list_farms(db=mock_db, limit=2, after_id=0, active_only=False)

        self.assertEqual(len(insurance_chain.filter_calls), 1)
        self.assertEqual(_in_clause_values(insurance_chain.filter_calls[0]), [10, 20])


class ListFarmsActiveOnlyTests(unittest.TestCase):
    def test_active_only_filters_farms_by_current_insurance_date_range(self):
        farms = [_fake_farm(1)]
        mock_db, farms_chain, _ = _build_mock_db(farms_all_result=farms)

        list_farms(db=mock_db, limit=None, after_id=0, active_only=True)

        # The farms query gets one extra .filter(Farm.farm_id.in_(subquery)).
        self.assertEqual(len(farms_chain.filter_calls), 1)
        criterion = farms_chain.filter_calls[0]
        self.assertEqual(getattr(criterion.operator, "__name__", ""), "in_op")

        # Compile the embedded subquery to SQL (with literal values inlined)
        # and confirm it actually brackets today between effectivity/expiry
        # -- avoids depending on ScalarSelect's internal attribute layout.
        compiled = str(criterion.compile(compile_kwargs={"literal_binds": True}))
        today_literal = date.today().isoformat()
        self.assertIn("effectivity_date", compiled)
        self.assertIn("expiry_date", compiled)
        self.assertIn(today_literal, compiled)

    def test_active_only_false_no_regression(self):
        # Mirrors what FastAPI actually passes list_farms() for a request
        # with no `active_only` query string (e.g. MonitoringModule.tsx's
        # call) -- FastAPI's own resolution of Query(False) to `False` is
        # framework behavior, not re-tested here (see module docstring note
        # on Query(..., ge=..., le=...) validation for the same reasoning);
        # this test exercises the already-resolved value directly, since
        # calling list_farms() as a plain function (bypassing FastAPI) would
        # otherwise leave `active_only` bound to the raw Query(False) marker
        # object instead of its resolved default.
        farms = [_fake_farm(1)]
        mock_db, farms_chain, _ = _build_mock_db(farms_all_result=farms)

        list_farms(db=mock_db, limit=None, after_id=0, active_only=False)

        self.assertEqual(farms_chain.filter_calls, [])

    def test_active_only_with_pagination_computes_filtered_total(self):
        # total/has_more must reflect the *filtered* count (farms_chain's
        # count, already scoped by the active-only filter applied before
        # .count() runs), not the whole unfiltered table.
        page = [_fake_farm(1)]
        mock_db, farms_chain, _ = _build_mock_db(farms_all_result=page, farms_count_result=1)

        result = list_farms(db=mock_db, limit=50, after_id=0, active_only=True)

        self.assertEqual(farms_chain.count_call_count, 1)
        self.assertEqual(result["total"], 1)
        self.assertFalse(result["has_more"])


class ListFarmsResponseShapeTests(unittest.TestCase):
    def test_data_row_uses_most_recent_insurance_record(self):
        # Regression check that the pagination refactor didn't disturb the
        # existing "most recent per farm" reduction (dict.setdefault() picks
        # the first record seen per farm_id, so the real query's
        # farm_id, effectivity_date DESC order matters -- simulated here by
        # returning the newer record first).
        today = date.today()
        newer = _fake_insurance(
            farm_id=1, policy_no="NEW",
            effectivity_date=today - timedelta(days=10),
            expiry_date=today + timedelta(days=355),
        )
        older = _fake_insurance(
            farm_id=1, policy_no="OLD",
            effectivity_date=today - timedelta(days=400),
            expiry_date=today - timedelta(days=35),
        )
        mock_db, _, _ = _build_mock_db(
            farms_all_result=[_fake_farm(1)],
            insurance_all_result=[newer, older],
        )

        result = list_farms(db=mock_db, limit=None, after_id=0, active_only=False)

        self.assertEqual(result["data"][0]["policy_no"], "NEW")
        self.assertEqual(
            result["data"][0]["effectivity_date"],
            (today - timedelta(days=10)).strftime("%m/%d/%Y"),
        )


if __name__ == "__main__":
    unittest.main()
