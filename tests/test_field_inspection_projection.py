"""Bridge projections receive the resolved member, never absence disguised as null."""
from dataclasses import dataclass
import pytest
from objectstate import Inherit, ObjectState, Unset, set_base_config_type
from objectstate.field_value import FieldValue, Value
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
    carrier = projected.to_semantic_carrier(include_values=True)
    assert carrier.raw_value == FieldValue.of(datum)
    assert carrier.resolved_value == FieldValue.of(datum)
    assert preview.text == ('Unset()' if isinstance(datum, Unset) else repr(datum))


@pytest.mark.parametrize('member', [Value(None), Value(False), Value(0), Value(''), Value('None'), Inherit(), Unset()])
def test_semantic_carrier_roundtrip_preserves_members(member):
    import json
    from python_introspect import dataclass_from_mapping, to_jsonable
    from formbridge.bridge.dto import UiObjectStateFieldSemanticCarrier
    original = UiObjectStateFieldSemanticCarrier(raw_value=member, resolved_value=member)
    decoded = dataclass_from_mapping(
        UiObjectStateFieldSemanticCarrier, json.loads(json.dumps(to_jsonable(original)))
    )
    assert decoded == original
    assert type(decoded.raw_value) is type(member)
    assert type(decoded.resolved_value) is type(member)


def test_excluding_payload_does_not_turn_it_into_null_or_erase_an_inheritance_request():
    from objectstate import LazyDataclassFactory, set_global_config
    set_base_config_type(Config)
    set_global_config(Config, Config(text='global'))
    lazy = LazyDataclassFactory.make_lazy_simple(Config)
    state = ObjectState(lazy(text=Inherit()))
    inspected = ObjectStateFieldSemanticProjection.of(state.fields.text)
    excluded = inspected.to_semantic_carrier(include_values=False)
    assert excluded.raw_value == Inherit()
    assert excluded.resolved_value == Unset()
    assert excluded.raw_value_preview.text == 'Inherit()'
    assert excluded.resolved_value_preview.text == "'global'"
    included = inspected.to_semantic_carrier(include_values=True)
    assert included.raw_value == Inherit()
    assert included.resolved_value == Value('global')


@pytest.mark.parametrize('member', [Value(None), Value(False), Value(0), Value(''), Inherit(), Unset()])
def test_compact_action_retains_member_tags_and_decodes(member):
    from python_introspect import dataclass_from_mapping
    from formbridge.bridge.dto import UiWidgetActionSummary, UiWidgetRect
    rect = UiWidgetRect(0, 0, 10, 10)
    action = UiWidgetActionSummary(
        path=(), path_id='root', child_index=None, class_name='QLineEdit',
        object_name='', accessible_name='', accessible_description='',
        label=None, visible=True, enabled=True, geometry=rect, global_geometry=rect,
        action_kinds=('text',), clickable=False, checkable=None, checked=None,
        current_index=None, current_text=None, item_count=None, tool_tip='',
        raw_value=member, resolved_value=member,
    )
    wire = action.compact_projection()
    assert wire['raw_value'] == ({'Value': {'value': member.value}} if isinstance(member, Value) else {type(member).__name__: {}})
    decoded = dataclass_from_mapping(UiWidgetActionSummary, wire)
    assert decoded == action


def test_field_list_compacts_concrete_data_without_converting_directives_or_null():
    from formbridge.bridge.dto import UiObjectStateFieldListQuery
    from formbridge.bridge.field_projection import ObjectStateFieldListProjector
    query = UiObjectStateFieldListQuery(max_value_chars=3)
    assert ObjectStateFieldListProjector.compact_value(query, Value(None)) == Value(None)
    assert ObjectStateFieldListProjector.compact_value(query, Inherit()) == Inherit()
    assert ObjectStateFieldListProjector.compact_value(query, Unset()) == Unset()
    assert ObjectStateFieldListProjector.compact_value(query, Value('abcdef')) == Value({
        'type': 'str', 'length': 6, 'truncated': True, 'preview': 'abc',
    })
