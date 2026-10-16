"""Bridge projections receive the resolved member, never absence disguised as null."""
from dataclasses import dataclass
import pytest
from objectstate import ObjectState, Unset, set_base_config_type
from formbridge.bridge.object_state import ObjectStateFieldSemanticProjection


@dataclass
class Config:
    text: str | None = None


@pytest.mark.parametrize('datum, expected_type', [(None, 'None'), (Unset(), 'Unset'), ('None', 'str'), ('Unset()', 'str'), ('', 'str')])
def test_resolved_projection_distinguishes_null_absence_and_literal_text(datum, expected_type):
    set_base_config_type(Config)
    state = ObjectState(Config(text=datum))
    projected = ObjectStateFieldSemanticProjection.of(state.fields.text)
    preview = projected.resolved_value_preview
    assert preview.type_name == expected_type
    assert preview.is_none == (datum is None)
    assert projected.resolved_value_is_none == (datum is None)
    assert projected.resolved_json_value == ('Unset()' if isinstance(datum, Unset) else datum)
    assert preview.text == ('Unset()' if isinstance(datum, Unset) else repr(datum))
