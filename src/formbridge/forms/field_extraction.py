"""Typed extraction rules for form-build metadata.

Replaces hand-written metadata string keys ('computed', 'project',
'initial_values') with one typed rule per dataclass field. The builder
calls the rule; it does not branch on strings or keep a second field roster.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import fields, Field
from typing import Generic, TypeVar

T = TypeVar("T")
Source = TypeVar("Source")

EXTRACTION_KEY = "field_extraction"


class FieldExtraction(ABC, Generic[T]):
    """One typed rule for extracting a form-build value from a source object."""

    @abstractmethod
    def extract(self, source: object, name: str, info: object, field_id: str) -> T:
        """Extract the value for one parameter from the source."""


class ProjectedExtraction(FieldExtraction[tuple[str, object]]):
    """Project each parameter into a (key, value) pair for a result mapping."""

    def __init__(self, project: Callable[[str, object, str], tuple[str, object]]) -> None:
        self.project = project

    def extract(self, source: object, name: str, info: object, field_id: str) -> tuple[str, object]:
        return self.project(name, info, field_id)


class InitialValuesExtraction(ProjectedExtraction):
    """A projected extraction that also applies initial-values overrides."""


class ComputedExtraction(FieldExtraction[object]):
    """Direct computation from the source, not per-parameter projection."""

    def __init__(self, compute: Callable[..., object]) -> None:
        self.compute = compute

    def extract(self, source: object, name: str, info: object, field_id: str) -> object:
        return self.compute(source)


def extraction_rule(dataclass_field: Field) -> FieldExtraction | None:
    """The typed extraction rule attached to a dataclass field, if any."""
    return dataclass_field.metadata.get(EXTRACTION_KEY)


def extract_all(result_class: type, source: object, parameters: object, field_id: str) -> dict:
    """Run every extraction rule on the result dataclass and collect the values."""
    result = {}
    for f in fields(result_class):
        rule = extraction_rule(f)
        if rule is None:
            continue
        for name, info in _parameter_items(parameters):
            value = rule.extract(source, name, info, field_id)
            if isinstance(rule, ProjectedExtraction):
                key, val = value
                result.setdefault(f.name, type(f.default_factory)() if f.default_factory is not type(None) else {})
                result[f.name][key] = val
            else:
                result[f.name] = value
    return result


def _parameter_items(parameters: object):
    """Iterate parameter names and their info objects."""
    if hasattr(parameters, 'items'):
        yield from parameters.items()
    elif hasattr(parameters, '__iter__'):
        yield from parameters
