"""Generic robustness sweep over every model's from_dict.

Schwab responses are inconsistent: "data" can be a list, a single object,
null, or absent; "meta"/"paging"/"count" can be null; any attribute can be
explicitly null rather than missing (so ``.get(key, default)`` defaults do
NOT fire). The library's contract is lenient parsing — a plausible payload
shape must never raise, and primitive-typed fields must come back as their
annotated primitive (never None, never the literal string "None").

These tests enumerate models dynamically so new models are covered the day
they're added.
"""

import dataclasses
import inspect
import typing

import pytest

from schwab_advisor import models as models_module


class _NullMap(dict):
    """A dict whose every lookup answers explicit JSON null (None).

    Simulates a payload where all attribute keys are present but null —
    the case where ``.get(key, default)`` defaults don't fire.
    """

    def get(self, key, default=None):
        return None

    def __contains__(self, key):
        return True


def _all_models():
    """Every dataclass in models.py with a from_dict classmethod."""
    out = []
    for name, obj in inspect.getmembers(models_module, inspect.isclass):
        if obj.__module__ != models_module.__name__:
            continue
        if not dataclasses.is_dataclass(obj):
            continue
        if name == "TokenResponse":  # strict-parse by design (auth-side)
            continue
        if hasattr(obj, "from_dict"):
            out.append(obj)
    return sorted(out, key=lambda c: c.__name__)


MODELS = _all_models()

ADVERSARIAL_PAYLOADS = [
    pytest.param({}, id="empty"),
    pytest.param({"data": None}, id="data-null"),
    pytest.param({"data": []}, id="data-empty-list"),
    pytest.param({"data": {}}, id="data-empty-dict"),
    pytest.param({"data": [{}]}, id="data-list-of-empty"),
    pytest.param({"data": {}, "meta": None}, id="meta-null"),
    pytest.param(
        {"data": [], "meta": {"paging": None, "count": None}},
        id="meta-nested-null",
    ),
    pytest.param({"data": [{"id": "1", "attributes": None}]}, id="attrs-null"),
    pytest.param(
        {"data": [{"id": "1", "attributes": _NullMap()}]},
        id="attrs-all-null-list",
    ),
    pytest.param(
        {"data": {"id": "1", "attributes": _NullMap()}},
        id="attrs-all-null-single",
    ),
    pytest.param(_NullMap(), id="top-level-all-null"),
]


def test_model_enumeration_is_nontrivial():
    assert len(MODELS) > 60, f"only found {len(MODELS)} models — sweep broken?"


@pytest.mark.parametrize("payload", ADVERSARIAL_PAYLOADS)
@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_from_dict_never_raises(model, payload):
    model.from_dict(payload)


def _primitive_annotation(field_type):
    """Return the bare primitive type for exactly-annotated fields."""
    if field_type in (str, int, float, bool):
        return field_type
    origin = typing.get_origin(field_type)
    if origin in (list, dict):
        return origin
    return None  # Optional / nested dataclass / unions: not enforced


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
def test_field_types_survive_all_null_payload(model):
    """With every attribute explicitly null, non-Optional primitive fields
    must still hold their annotated type — not None, and str fields must
    not become the literal "None"."""
    instance = model.from_dict({"data": [{"attributes": _NullMap()}]})
    if isinstance(instance, model) is False:  # pragma: no cover
        pytest.skip("from_dict returned a different type")
    hints = typing.get_type_hints(model)
    for f in dataclasses.fields(model):
        expected = _primitive_annotation(hints.get(f.name))
        if expected is None:
            continue
        value = getattr(instance, f.name)
        if expected is float:
            assert isinstance(value, (int, float)) and not isinstance(
                value, bool
            ), f"{model.__name__}.{f.name} = {value!r}, want number"
        else:
            assert isinstance(
                value, expected
            ), f"{model.__name__}.{f.name} = {value!r}, want {expected.__name__}"
        if expected is str:
            assert value != "None", (
                f"{model.__name__}.{f.name} stringified a JSON null"
            )


class TestTypedCollectionsTolerateJunk:
    """The v0.3.0 typed collections (positions, balances, lots) parse
    nested ARRAYS, which the generic sweep above only exercises at the
    envelope level. A malformed element inside one of those arrays must
    be skipped, not crash the whole response — Schwab has been observed
    returning nulls inside collections that the spec types as objects.
    """

    def test_position_detail_skips_non_dict_entries(self):
        from schwab_advisor.models import PositionDetailResponse

        resp = PositionDetailResponse.from_dict({
            "data": {"attributes": {
                "positions": [None, "junk", 7, {"symbol": "AAPL", "quantity": 3}],
                "totalPositions": "not-an-object",
            }},
        })
        assert len(resp.positions) == 1
        assert resp.positions[0].symbol == "AAPL"
        assert resp.total_positions is None  # scalar where an object was typed

    def test_balances_list_skips_non_dict_entries(self):
        from schwab_advisor.models import BalanceListResponse

        resp = BalanceListResponse.from_dict({
            "data": {"attributes": {
                "balances": [None, {"formattedAccount": "1234", "cash": 5}],
                "errors": "not-a-list",
                "totalBalances": None,
            }},
        })
        assert len(resp.balances) == 1
        assert resp.errors == []
        assert resp.total_balances is None

    def test_positions_list_skips_non_dict_entries(self):
        from schwab_advisor.models import PositionListResponse

        resp = PositionListResponse.from_dict({
            "data": {"attributes": {"positions": [None, {"symbol": "MSFT"}]}},
        })
        assert len(resp.positions) == 1
        assert resp.positions[0].symbol == "MSFT"

    def test_ugl_lots_skip_non_dict_entries(self):
        from schwab_advisor.models import UglPositionLotsResponse

        resp = UglPositionLotsResponse.from_dict({
            "data": {"attributes": {
                "positions": [
                    None,
                    {"positionId": "p1", "lots": [None, {"lotId": "L1"}]},
                ],
                "errors": ["not-a-dict"],
            }},
        })
        assert len(resp.positions) == 1
        assert [lot.lot_id for lot in resp.positions[0].lots] == ["L1"]
        assert resp.invalid_positions == []

    def test_rgl_transaction_lots_skip_non_dict_entries(self):
        from schwab_advisor.models import RglTransaction

        txn = RglTransaction.from_dict({
            "transactionId": "t1",
            "transactionLots": [None, 3, {"lotId": "L9"}],
        })
        assert [lot.lot_id for lot in txn.transaction_lots] == ["L9"]

    def test_summaries_tolerate_scalars(self):
        from schwab_advisor.models import CostBasisRglResponse, CostBasisUglResponse

        rgl = CostBasisRglResponse.from_dict(
            {"data": {"attributes": {"summary": "n/a", "transactions": []}}})
        ugl = CostBasisUglResponse.from_dict(
            {"data": {"attributes": {"summary": None, "positions": []}}})
        assert rgl.summary is None and ugl.summary is None
