"""Preview formatter registration behavior."""

from dataclasses import dataclass, field

import pytest
from objectstate.lazy_factory import LazyDataclassFactory

from formbridge.protocols.preview_formatter import PreviewFormatterRegistry


def test_preview_formatter_resolves_nearest_nominal_base_registration() -> None:
    class BaseConfig:
        pass

    class SpecializedConfig(BaseConfig):
        pass

    PreviewFormatterRegistry.register(
        BaseConfig,
        lambda _config, field_name: f"base:{field_name}",
    )

    assert PreviewFormatterRegistry.format_field(SpecializedConfig(), "value") == ("base:value")


def test_preview_formatter_does_not_hide_host_formatter_failures() -> None:
    class BrokenConfig:
        pass

    def broken_formatter(_config: object, _field_name: str) -> str:
        raise RuntimeError("formatter failed")

    PreviewFormatterRegistry.register(BrokenConfig, broken_formatter)

    with pytest.raises(RuntimeError, match="formatter failed"):
        PreviewFormatterRegistry.format_field(BrokenConfig(), "value")


def test_preview_formatter_ignores_lazy_wrapper_registration() -> None:
    @dataclass
    class BaseConfig:
        value: int = 0

    lazy_type = LazyDataclassFactory.make_lazy_simple(
        BaseConfig,
        "LazyPreviewFormatterRegistryBaseConfig",
    )
    PreviewFormatterRegistry.register(
        BaseConfig,
        lambda _config, _field_name: "base",
    )
    PreviewFormatterRegistry.register(
        lazy_type,
        lambda _config, _field_name: "copied",
    )

    assert PreviewFormatterRegistry.format_field(lazy_type(), "value") == "base"


def test_preview_formatter_registration_rejects_a_second_formatter_for_one_type() -> None:
    class OnceConfig:
        pass

    def formatter(_config: object, field_name: str) -> str:
        return f"first:{field_name}"

    PreviewFormatterRegistry.register(OnceConfig, formatter)
    PreviewFormatterRegistry.register(OnceConfig, formatter)

    with pytest.raises(ValueError, match="OnceConfig already has a preview formatter"):
        PreviewFormatterRegistry.register(OnceConfig, lambda _config, _field_name: "second")
    assert PreviewFormatterRegistry.format_field(OnceConfig(), "value") == "first:value"


def test_group_heading_default_reads_the_objectstate_declaration() -> None:
    from objectstate.lazy_factory import abbreviation, get_group_abbreviation

    from formbridge.strategies.preview_formatting import FormattingConfig

    @abbreviation("cfg")
    @dataclass
    class HeadedConfig:
        value: int = 0

    class SpecializedHeadedConfig(HeadedConfig):
        pass

    lazy_type = LazyDataclassFactory.make_lazy_simple(HeadedConfig, "LazyHeadedConfig")
    heading = FormattingConfig().container_abbr_func

    assert heading is get_group_abbreviation
    assert heading(HeadedConfig) == "cfg"
    assert heading(SpecializedHeadedConfig) == "cfg"
    assert heading(lazy_type) == "cfg"


def test_preview_groups_root_and_nested_fields_by_their_dotted_parent(monkeypatch) -> None:
    from objectstate import ObjectState, config

    from formbridge.strategies.preview_formatting import (
        FormattingConfig,
        ObjectStatePreviewFormattingService,
    )

    @dataclass
    class PreviewChild:
        value: int = 2

    @dataclass
    class PreviewRoot:
        value: int = 1
        child: PreviewChild = field(default_factory=PreviewChild)

    monkeypatch.setattr(config, "_base_config_type", PreviewRoot)
    state = ObjectState(PreviewRoot())
    service = ObjectStatePreviewFormattingService(
        FormattingConfig(container_abbr_func=lambda _owner: "child")
    )

    segments = service.collect_and_render(
        state, ("value", "child.value"), {}, lambda request: str(request.value)
    )

    assert segments == [
        ("root", None, ""), ("{", None, ""), ("1", "value", ""), ("}", None, ""),
        ("child", "child", " | "), ("{", None, ""),
        ("2", "child.value", ""), ("}", None, ""),
    ]
