"""Static gates for the toolkit-neutral form model."""

from __future__ import annotations

from pathlib import Path


def test_union_and_nested_field_semantics_have_no_parallel_fallbacks():
    """Union and field identity remain derived from declarations."""
    forms_root = Path(__file__).parents[1] / "src" / "formbridge" / "forms"
    parameter_info_source = (forms_root / "parameter_info_types.py").read_text()
    parameter_type_source = (forms_root / "parameter_type_utils.py").read_text()
    service_source = (forms_root / "parameter_form_service.py").read_text()

    assert "get_origin(param_type) is Union" not in parameter_info_source
    assert "get_origin(param_type) is Union" not in parameter_type_source
    assert "get_obj_type_for_param" not in parameter_type_source
    assert "resolve_union_type" not in parameter_type_source
    assert "get_field_path_with_fail_loud" not in service_source
    assert "__name__.lower().replace('config', '')" not in service_source
    assert "Handle Union types" not in service_source
