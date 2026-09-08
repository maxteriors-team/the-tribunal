"""Tests for the exact tree-wrap measurement stored on a placed design item.

A saved design is customer money: it is re-opened months later and re-priced
from these numbers. The schema is the only thing standing between a hand-built
request and a quote, so these cover what it must accept (a real measurement, and
every design drawn before this feature existed) and what it must refuse
(impossible dimensions, unknown shapes, negative prices, stray fields).
"""

import pytest
from pydantic import ValidationError

from app.schemas.lighting_project import PlacedItemSchema

MEASURED = {
    "shape": "evergreen",
    "lightType": "mini",
    "heightFt": 20,
    "rowSpacingIn": 12,
    "radiusFt": 6,
    "feetPerUnit": 25,
    "pricingMode": "unit",
    "unitPrice": 39.99,
}


def placed(**overrides):
    """A placed decor item, measured unless a test says otherwise."""
    return {
        "id": "item-1",
        "productId": "cat-trees-medium",
        "at": {"x": 100, "y": 200},
        "sizePx": 120,
        **overrides,
    }


class TestWrapSpecAccepts:
    def test_stores_a_full_measurement(self):
        item = PlacedItemSchema.model_validate(placed(wrap=MEASURED))
        assert item.wrap is not None
        assert item.wrap.shape == "evergreen"
        assert item.wrap.height_ft == 20
        assert item.wrap.radius_ft == 6
        assert item.wrap.unit_price == 39.99

    def test_accepts_a_design_drawn_before_this_feature_existed(self):
        # Every design already saved has no `wrap`. Those must keep loading, and
        # keep pricing by size band exactly as they always have.
        assert PlacedItemSchema.model_validate(placed()).wrap is None

    def test_round_trips_the_names_the_browser_uses(self):
        item = PlacedItemSchema.model_validate(placed(wrap=MEASURED))
        dumped = item.model_dump(by_alias=True)["wrap"]
        assert dumped["heightFt"] == 20
        assert dumped["rowSpacingIn"] == 12
        # Reloading its own output must give back the same measurement.
        assert PlacedItemSchema.model_validate(placed(wrap=dumped)).wrap == item.wrap

    def test_keeps_a_measurement_that_is_not_priced_yet(self):
        # A rep who measures but has not typed a rate must not lose their work;
        # the tree stays on band pricing until they do.
        item = PlacedItemSchema.model_validate(
            placed(wrap={**MEASURED, "unitPrice": None}),
        )
        assert item.wrap is not None
        assert item.wrap.unit_price is None
        assert item.wrap.height_ft == 20

    @pytest.mark.parametrize("shape", ["evergreen", "deciduous", "trunk", "branch", "bush"])
    def test_accepts_every_shape_a_rep_can_pick(self, shape):
        item = PlacedItemSchema.model_validate(placed(wrap={**MEASURED, "shape": shape}))
        assert item.wrap is not None
        assert item.wrap.shape == shape


class TestWrapSpecRefuses:
    @pytest.mark.parametrize(
        ("field", "value", "why"),
        [
            ("heightFt", 0, "a zero-height tree is not a tree"),
            ("heightFt", -20, "negative height"),
            ("heightFt", 99999, "taller than any crew can reach"),
            ("rowSpacingIn", 0, "zero spacing means infinite rows"),
            ("radiusFt", -6, "negative radius"),
            ("unitPrice", -5, "a negative rate would credit the customer"),
            ("branchCount", 0, "wrapping no branches"),
            ("branchCount", 9999, "more limbs than a tree has"),
        ],
    )
    def test_refuses_impossible_dimensions(self, field, value, why):
        with pytest.raises(ValidationError):
            PlacedItemSchema.model_validate(placed(wrap={**MEASURED, field: value}))

    def test_refuses_a_shape_it_cannot_price(self):
        with pytest.raises(ValidationError):
            PlacedItemSchema.model_validate(placed(wrap={**MEASURED, "shape": "palm"}))

    def test_refuses_a_light_type_it_cannot_price(self):
        with pytest.raises(ValidationError):
            PlacedItemSchema.model_validate(placed(wrap={**MEASURED, "lightType": "laser"}))

    def test_refuses_an_unknown_billing_basis(self):
        with pytest.raises(ValidationError):
            PlacedItemSchema.model_validate(placed(wrap={**MEASURED, "pricingMode": "free"}))

    def test_refuses_stray_fields(self):
        # A hand-built payload must not smuggle anything past the schema.
        with pytest.raises(ValidationError):
            PlacedItemSchema.model_validate(placed(wrap={**MEASURED, "discount": 0.5}))

    def test_requires_the_dimensions_that_define_a_measurement(self):
        for missing in ("shape", "heightFt", "rowSpacingIn", "pricingMode"):
            incomplete = {k: v for k, v in MEASURED.items() if k != missing}
            with pytest.raises(ValidationError):
                PlacedItemSchema.model_validate(placed(wrap=incomplete))
