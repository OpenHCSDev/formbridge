from dataclasses import dataclass, field

from formbridge.services.widget_tree_projection_config import (
    COMPACT_FIELD_PROJECTION_METADATA_KEY,
    CompactFieldProjection,
    compact_dataclass_projection,
)


@dataclass(frozen=True)
class _ProjectionExample:
    required_empty: str = field(
        metadata={
            COMPACT_FIELD_PROJECTION_METADATA_KEY: CompactFieldProjection(
                includes=lambda _owner, _value: True
            )
        }
    )
    ordinary_empty: str = ""
    enabled: bool = False
    selected: bool = field(
        default=False,
        metadata={
            COMPACT_FIELD_PROJECTION_METADATA_KEY: CompactFieldProjection(
                includes=lambda owner, value: value or owner.enabled
            )
        },
    )


def test_compact_dataclass_projection_uses_field_owned_predicates():
    value = _ProjectionExample(
        required_empty="",
        enabled=True,
        selected=False,
    )

    assert compact_dataclass_projection(value) == {
        "required_empty": "",
        "enabled": True,
        "selected": False,
    }


def test_compact_dataclass_projection_omits_default_empty_values():
    value = _ProjectionExample(required_empty="")

    assert compact_dataclass_projection(value) == {"required_empty": ""}


def test_required_empty_fields_survive_even_an_excluding_policy():
    @dataclass
    class RequiredValues:
        empty: str
        absent: None
        disabled: bool = field(metadata={
            COMPACT_FIELD_PROJECTION_METADATA_KEY: CompactFieldProjection(
                includes=lambda _owner, _value: False
            )
        })

    value = RequiredValues('', None, False)
    assert compact_dataclass_projection(value) == {
        'empty': '', 'absent': None, 'disabled': False
    }


def test_empty_values_differing_from_defaults_remain_distinct():
    @dataclass
    class OptionalValues:
        enabled: bool | None = None
        name: str = 'default'
        entries: tuple = field(default_factory=tuple)

    assert compact_dataclass_projection(OptionalValues(False, '')) == {
        'enabled': False, 'name': '', 'entries': ()
    }
