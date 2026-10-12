import pytest

from formbridge.services.pattern_data_manager import PatternDataManager


def _func(image):
    return image


def test_pattern_entries_are_callables_or_callable_kwargs_pairs():
    assert PatternDataManager.extract_func_and_kwargs(_func) == (_func, {})
    assert PatternDataManager.extract_func_and_kwargs((_func, {"a": 1})) == (_func, {"a": 1})


@pytest.mark.parametrize("entry", ((_func, {}, "extra"), ("name", {}), None))
def test_malformed_pattern_entry_is_refused_not_dropped(entry):
    with pytest.raises(TypeError):
        PatternDataManager.extract_func_and_kwargs(entry)
    assert PatternDataManager.validate_pattern_structure([entry]) is False
