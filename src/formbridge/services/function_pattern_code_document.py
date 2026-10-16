"""Function-pattern code document roundtrip services.

This module owns the non-widget semantics for pycodifying function patterns,
preserving stable function-entry ObjectState tokens, and servicing code-mode
documents for nested function scopes.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, get_type_hints

from objectstate import ObjectState, ObjectStateRegistry, ScopeKey, semantic_values_equal
from python_introspect import (
    callable_declaration_kwargs,
    parameter_exclusions,
    set_parameter_exclusions,
)

from formbridge.forms.parameter_value_contracts import ParameterValue
from formbridge.pattern_metadata import PatternScopeToken
from formbridge.protocols.codegen_provider import get_codegen_provider
from formbridge.services.function_navigation import FunctionPatternField
from formbridge.services.pattern_data_manager import FUNC_EDITOR_PATTERN_TOKENS_META_KEY
from formbridge.services.scope_token_service import (
    ScopeTokenGenerator,
    reconcile_occurrence_tokens,
)
from formbridge.services.window_code_document import (
    PYTHON_MIME_TYPE,
    WindowCodeDocument,
    WindowCodeDocumentDriver,
)

logger = logging.getLogger(__name__)
FUNCTION_PATTERN_AUTHORITY_ATTR = "__function_pattern_authority__"


def function_pattern_authority(func):
    """Return the real callable authority for an editable function-pattern view."""
    return getattr(func, FUNCTION_PATTERN_AUTHORITY_ATTR, func)


FunctionAuthority = Callable[..., ParameterValue]
"""Callable identity owned by a function-pattern entry."""


FunctionKwargs = dict[str, ParameterValue]
FunctionPatternItem = tuple[FunctionAuthority, FunctionKwargs]
FunctionPatternList = list[FunctionPatternItem]
FunctionPatternByKey = dict[str, FunctionPatternList]
PatternTokens = list[str] | dict[str, list[str]]
PatternSourceValue = (
    FunctionAuthority | FunctionPatternItem | FunctionPatternList | FunctionPatternByKey
)


class FunctionPatternRoundTripError(RuntimeError):
    """Raised when a function-pattern code document cannot be serviced."""


@dataclass(frozen=True, slots=True)
class TokenizedFunctionEntry:
    """Function pattern entry paired with its stable ObjectState token."""

    func: FunctionAuthority
    kwargs: FunctionKwargs
    token: str


@dataclass(frozen=True, slots=True)
class FunctionPatternValue:
    """Current callable and kwargs for one stable function token."""

    func: FunctionAuthority
    kwargs: FunctionKwargs


class EditableFunctionPatternCallable:
    """Callable view whose signature includes explicit function-pattern kwargs."""

    def __init__(
        self,
        authority: FunctionAuthority,
        kwargs: Mapping[str, ParameterValue] | None,
    ) -> None:
        self.__function_pattern_authority__ = authority
        self.__name__ = getattr(authority, "__name__", type(authority).__name__)
        self.__qualname__ = getattr(authority, "__qualname__", self.__name__)
        self.__module__ = getattr(authority, "__module__", type(authority).__module__)
        self.__doc__ = getattr(authority, "__doc__", None)
        self.__wrapped__ = authority
        self.__annotations__ = self._annotations(authority, kwargs or {})
        self.__signature__ = self._signature(authority, kwargs or {})
        hidden = parameter_exclusions(authority).difference(kwargs or ())
        if hidden:
            set_parameter_exclusions(self, hidden)

    def __call__(self, *args: ParameterValue, **kwargs: ParameterValue):
        return self.__function_pattern_authority__(*args, **kwargs)

    @classmethod
    def for_entry(
        cls,
        func: FunctionAuthority,
        kwargs: Mapping[str, ParameterValue] | None,
    ) -> FunctionAuthority:
        """Return an editable callable view when kwargs extend the signature."""
        if not kwargs:
            return func
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):
            return func
        if all(name in signature.parameters for name in kwargs) and not parameter_exclusions(
            func
        ).intersection(kwargs):
            return func
        return cls(func, kwargs)

    @staticmethod
    def _signature(
        authority: FunctionAuthority,
        kwargs: Mapping[str, ParameterValue],
    ) -> inspect.Signature:
        signature = inspect.signature(authority)
        resolved_annotations = EditableFunctionPatternCallable._resolved_annotations(authority)
        parameters = [
            (
                parameter.replace(annotation=resolved_annotations[name])
                if name in resolved_annotations
                else parameter
            )
            for name, parameter in signature.parameters.items()
        ]
        existing = set(signature.parameters)
        for name, value in kwargs.items():
            if name in existing:
                continue
            parameters.append(
                inspect.Parameter(
                    name,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=value,
                    annotation=EditableFunctionPatternCallable._annotation(value),
                )
            )
        return signature.replace(parameters=parameters)

    @staticmethod
    def _annotations(
        authority: FunctionAuthority,
        kwargs: Mapping[str, ParameterValue],
    ) -> dict[str, Any]:
        annotations = EditableFunctionPatternCallable._resolved_annotations(authority)
        for name, value in kwargs.items():
            annotations.setdefault(
                name,
                EditableFunctionPatternCallable._annotation(value),
            )
        return annotations

    @staticmethod
    def _resolved_annotations(authority: FunctionAuthority) -> dict[str, Any]:
        try:
            return get_type_hints(authority, include_extras=True)
        except Exception:
            return dict(getattr(authority, "__annotations__", {}))

    @staticmethod
    def _annotation(value: ParameterValue) -> Any:
        if value is None:
            return Any
        if isinstance(value, tuple):
            element_types = {type(item) for item in value if item is not None}
            if len(element_types) == 1:
                return tuple[next(iter(element_types)), ...]
            return tuple[Any, ...]
        return type(value)


@dataclass(frozen=True, slots=True)
class FunctionPatternParameterExclusions:
    """Editable-parameter exclusions for function-pattern ObjectStates."""

    names: tuple[str, ...]

    @classmethod
    def from_callable(
        cls,
        func: FunctionAuthority,
    ) -> FunctionPatternParameterExclusions:
        ordered_names = cls._ordered_names(
            cls._first_positional_parameter_name(func),
            tuple(parameter_exclusions(func)),
        )
        return cls(names=ordered_names)

    @staticmethod
    def _first_positional_parameter_name(func: FunctionAuthority) -> str | None:
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):
            return None

        for param_name in signature.parameters:
            if param_name in ("self", "cls"):
                continue
            return param_name
        return None

    @staticmethod
    def _ordered_names(
        positional_name: str | None,
        declared_names: tuple[str, ...],
    ) -> tuple[str, ...]:
        names: list[str] = []
        if positional_name is not None:
            names.append(positional_name)
        names.extend(declared_names)
        return tuple(dict.fromkeys(names))

    def as_list(self) -> list[str] | None:
        if not self.names:
            return None
        return list(self.names)


@dataclass(frozen=True, slots=True)
class FunctionPatternChildScopeAddress:
    """Generic ObjectState child scope for one function-pattern entry."""

    scope_id: str
    parent_scope_id: str
    token: str

    @classmethod
    def parse(cls, scope_id: str) -> FunctionPatternChildScopeAddress:
        scope = ScopeKey(scope_id)
        if scope.depth < 2:
            raise FunctionPatternRoundTripError(
                "Function-pattern child scopes must have a parent scope and "
                f"an entry token; got {scope_id!r}."
            )
        return cls(
            scope_id=scope,
            parent_scope_id=scope.parent,
            token=scope.last,
        )


class FunctionPatternCodeDocumentService:
    """Code/document and ObjectState semantics for function patterns."""

    pattern_assignment_name: ClassVar[str] = "pattern"
    token_prefix: ClassVar[str] = FunctionPatternField.scope_token_prefix()

    def __init__(self) -> None:
        self._func_token_generator = ScopeTokenGenerator(
            self.token_prefix,
            attr_name=None,
        )

    @classmethod
    def sanitize_pattern_kwargs(
        cls,
        kwargs: Mapping[str, ParameterValue] | None,
    ) -> FunctionKwargs:
        """Validate kwargs and reject internal scope-token metadata."""
        if kwargs is None:
            return {}
        if PatternScopeToken.key_in(kwargs):
            raise FunctionPatternRoundTripError(
                "Function kwargs contain internal scope-token metadata. "
                "Tokens must be stored in ObjectState metadata."
            )
        clean_kwargs: FunctionKwargs = {}
        for key, value in kwargs.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"Function kwargs must be keyed by parameter name; got key {key!r}."
                )
            clean_kwargs[key] = value
        return clean_kwargs

    @classmethod
    def function_and_kwargs(
        cls,
        func_item,
    ) -> FunctionPatternItem | None:
        """Return one normalized function-pattern entry."""
        if isinstance(func_item, tuple) and len(func_item) == 2 and callable(func_item[0]):
            func, kwargs = func_item
            if not isinstance(kwargs, Mapping):
                raise TypeError("Function-pattern tuple entries must carry a kwargs mapping.")
            return func, cls.sanitize_pattern_kwargs(kwargs)

        if callable(func_item):
            return func_item, {}

        return None

    def generate_complete_function_pattern_code(
        self,
        pattern_data: PatternSourceValue,
        *,
        clean_mode: bool = False,
    ) -> str:
        """Render a complete Python document for a function pattern."""
        provider = get_codegen_provider()
        if provider is None:
            raise FunctionPatternRoundTripError(
                "No codegen provider registered. Call register_codegen_provider(...)."
            )
        return provider.render_assignment(
            pattern_data,
            assignment_name=self.pattern_assignment_name,
            header="# Edit this function pattern and save to apply changes",
            clean_mode=clean_mode,
        )

    def pattern_from_source(self, source: str) -> PatternSourceValue:
        """Parse a function-pattern source document and return `pattern`."""
        if not isinstance(source, str):
            raise TypeError(
                f"Function-pattern source must be a string; got {type(source).__name__}."
            )

        namespace = {}
        exec(source, namespace)

        if self.pattern_assignment_name not in namespace:
            raise FunctionPatternRoundTripError(
                f"No {self.pattern_assignment_name!r} assignment found in code."
            )
        return namespace[self.pattern_assignment_name]

    def normalize_function_list(
        self,
        func_list,
        *,
        seen_tokens: set[str] | None = None,
        seed_tokens: list[str] | None = None,
    ) -> tuple[FunctionPatternList, list[str]]:
        """Normalize function entries and align them with stable tokens."""
        active_seen_tokens = seen_tokens if seen_tokens is not None else set()
        active_seed_tokens = seed_tokens if seed_tokens is not None else []

        normalized = self._normalized_entries(func_list)
        tokens: list[str] = []
        for index, _entry in enumerate(normalized):
            seed_token = (
                str(active_seed_tokens[index])
                if index < len(active_seed_tokens) and active_seed_tokens[index]
                else None
            )
            token = seed_token or self._func_token_generator.ensure()
            if token in active_seen_tokens:
                token = self._func_token_generator.ensure()
            active_seen_tokens.add(token)
            tokens.append(str(token))

        return normalized, tokens

    def seed_func_token_generator(self, tokens: PatternTokens) -> None:
        """Seed token generator from canonical sidecar metadata tokens."""
        token_values: list[str] = []
        if isinstance(tokens, list):
            token_values.extend(str(token) for token in tokens if token)
        elif isinstance(tokens, dict):
            for channel_tokens in tokens.values():
                token_values.extend(str(token) for token in channel_tokens if token)
        if token_values:
            self._func_token_generator.seed_from_tokens(token_values)

    def ensure_token(self) -> str:
        """Return a fresh function-entry token."""
        return self._func_token_generator.ensure()

    def tokens_for_pattern(
        self,
        pattern: PatternSourceValue | None,
    ) -> PatternTokens:
        """Return fresh occurrence-owned tokens for a new function pattern."""

        seen_tokens: set[str] = set()
        if isinstance(pattern, dict):
            tokens_by_key: dict[str, list[str]] = {}
            for key, func_list in pattern.items():
                _normalized, tokens = self.normalize_function_list(
                    func_list,
                    seen_tokens=seen_tokens,
                )
                tokens_by_key[str(key)] = tokens
            return tokens_by_key
        _normalized, tokens = self.normalize_function_list(
            pattern,
            seen_tokens=seen_tokens,
        )
        return tokens

    def reconcile_pattern_tokens(
        self,
        previous_pattern: PatternSourceValue | None,
        previous_tokens: PatternTokens | None,
        next_pattern: PatternSourceValue | None,
    ) -> PatternTokens:
        """Reconcile complete-pattern tokens by declaration and callable authority."""

        existing_tokens = previous_tokens or []
        self.seed_func_token_generator(existing_tokens)
        claimed_tokens: set[str] = set()
        if isinstance(next_pattern, dict):
            previous_by_key = previous_pattern if isinstance(previous_pattern, dict) else {}
            tokens_by_key = existing_tokens if isinstance(existing_tokens, dict) else {}
            return {
                str(key): self._reconcile_function_list_tokens(
                    previous_by_key.get(str(key)),
                    tokens_by_key.get(str(key), []),
                    func_list,
                    claimed_tokens=claimed_tokens,
                )
                for key, func_list in next_pattern.items()
            }
        return self._reconcile_function_list_tokens(
            previous_pattern if not isinstance(previous_pattern, dict) else [],
            existing_tokens if isinstance(existing_tokens, list) else [],
            next_pattern,
            claimed_tokens=claimed_tokens,
        )

    def _reconcile_function_list_tokens(
        self,
        previous_list,
        previous_tokens: list[str],
        next_list,
        *,
        claimed_tokens: set[str],
    ) -> list[str]:
        """Reconcile one list-shaped region of a function pattern."""

        previous_entries = self._normalized_entries(previous_list)
        next_entries = self._normalized_entries(next_list)
        return reconcile_occurrence_tokens(
            previous_entries,
            previous_tokens,
            next_entries,
            same_declaration=self.same_function_declaration,
            occurrence_authorities=lambda entry: (function_pattern_authority(entry[0]),),
            token_factory=self.ensure_token,
            claimed_tokens=claimed_tokens,
        )

    @classmethod
    def _normalized_entries(cls, func_list) -> FunctionPatternList:
        """Return normalized entries without assigning occurrence identity."""

        if (
            isinstance(func_list, tuple)
            and len(func_list) == 2
            and callable(func_list[0])
            and isinstance(func_list[1], Mapping)
        ) or callable(func_list):
            values = [func_list]
        elif not func_list:
            return []
        elif isinstance(func_list, list):
            values = func_list
        else:
            raise FunctionPatternRoundTripError(
                "Function pattern reconciliation requires a callable, "
                "(callable, kwargs) tuple, list, or empty value."
            )
        entries: FunctionPatternList = []
        for index, value in enumerate(values):
            entry = cls.function_and_kwargs(value)
            if entry is None:
                raise FunctionPatternRoundTripError(
                    f"Unsupported function-pattern entry at index {index}: {value!r}."
                )
            entries.append(entry)
        return entries

    def canonical_function_scope_tokens(
        self,
        *,
        parent_scope_id: str | None,
        func_list,
        candidate_tokens: list[str],
    ) -> list[str]:
        """Return candidate tokens when they still name registered child states."""
        if self.function_scope_tokens_match(
            parent_scope_id=parent_scope_id,
            func_list=func_list,
            tokens=candidate_tokens,
        ):
            return candidate_tokens
        return self.existing_function_scope_tokens(
            parent_scope_id=parent_scope_id,
            func_list=func_list,
        )

    def existing_function_scope_tokens(
        self,
        *,
        parent_scope_id: str | None,
        func_list,
    ) -> list[str]:
        """Return existing child ObjectState tokens aligned with a function list."""
        if not parent_scope_id:
            return []

        parent_scope = ScopeKey(parent_scope_id)
        candidate_states = [
            state
            for state in ObjectStateRegistry.get_all()
            if isinstance(state.scope_id, str) and parent_scope.strictly_contains(state.scope_id)
        ]
        if not candidate_states:
            return []

        available = sorted(
            candidate_states,
            key=lambda state: ScopeKey(state.scope_id).last,
        )
        tokens: list[str] = []
        used_scope_ids: set[str] = set()
        item_list = func_list if isinstance(func_list, list) else [func_list]
        for item in item_list:
            entry = self.function_and_kwargs(item)
            if entry is None:
                continue
            func, _kwargs = entry
            match = next(
                (
                    state
                    for state in available
                    if state.scope_id not in used_scope_ids
                    and self.same_function_authority(state.object_instance, func)
                ),
                None,
            )
            if match is None:
                return []
            used_scope_ids.add(match.scope_id)
            tokens.append(ScopeKey(match.scope_id).last)
        return tokens

    def function_scope_tokens_match(
        self,
        *,
        parent_scope_id: str | None,
        func_list,
        tokens: list[str],
    ) -> bool:
        """Check whether tokens point at registered ObjectStates for funcs."""
        if not parent_scope_id or not tokens:
            return False

        item_list = func_list if isinstance(func_list, list) else [func_list]
        if len(tokens) < len(item_list):
            return False

        for index, item in enumerate(item_list):
            entry = self.function_and_kwargs(item)
            if entry is None:
                continue
            func, _kwargs = entry
            state = ObjectStateRegistry.get_by_scope(ScopeKey(parent_scope_id).child(tokens[index]))
            if state is None:
                return False
            if not self.same_function_authority(state.object_instance, func):
                return False
        return True

    @staticmethod
    def same_function_authority(left, right) -> bool:
        """Return whether two callable objects represent the same authority."""
        left = function_pattern_authority(left)
        right = function_pattern_authority(right)
        left_declaration = inspect.unwrap(left)
        right_declaration = inspect.unwrap(right)
        return left_declaration is right_declaration or semantic_values_equal(
            left_declaration,
            right_declaration,
        )

    @classmethod
    def same_function_declaration(
        cls,
        left: FunctionPatternItem,
        right: FunctionPatternItem,
    ) -> bool:
        """Return whether callable authority and declared kwargs are unchanged."""

        return cls.same_function_authority(
            left[0],
            right[0],
        ) and semantic_values_equal(
            callable_declaration_kwargs(
                function_pattern_authority(left[0]),
                left[1],
                values_equal=semantic_values_equal,
            ),
            callable_declaration_kwargs(
                function_pattern_authority(right[0]),
                right[1],
                values_equal=semantic_values_equal,
            ),
        )

    @classmethod
    def iter_tokenized_entries(
        cls,
        pattern: FunctionPatternList | FunctionPatternByKey,
        tokens: PatternTokens,
    ) -> list[TokenizedFunctionEntry]:
        """Return flat (func, kwargs, token) entries from pattern + tokens."""
        entries: list[TokenizedFunctionEntry] = []
        if isinstance(pattern, dict):
            token_map = tokens if isinstance(tokens, dict) else {}
            for channel_key, items in pattern.items():
                channel_items = items if isinstance(items, list) else [items]
                channel_tokens = token_map.get(str(channel_key), [])
                for index, item in enumerate(channel_items):
                    entry = cls.function_and_kwargs(item)
                    if entry is None:
                        continue
                    token = (
                        str(channel_tokens[index])
                        if index < len(channel_tokens) and channel_tokens[index]
                        else ""
                    )
                    entries.append(
                        TokenizedFunctionEntry(
                            func=entry[0],
                            kwargs=entry[1],
                            token=token,
                        )
                    )
            return entries

        item_list = pattern if isinstance(pattern, list) else [pattern]
        token_list = tokens if isinstance(tokens, list) else []
        for index, item in enumerate(item_list):
            entry = cls.function_and_kwargs(item)
            if entry is None:
                continue
            token = str(token_list[index]) if index < len(token_list) and token_list[index] else ""
            entries.append(
                TokenizedFunctionEntry(
                    func=entry[0],
                    kwargs=entry[1],
                    token=token,
                )
            )
        return entries

    def update_function_object_states(
        self,
        *,
        parent_scope_id: str | None,
        old_entries: list[TokenizedFunctionEntry],
        new_entries: list[TokenizedFunctionEntry],
    ) -> None:
        """Update existing function ObjectStates from a code-mode edit."""
        if not parent_scope_id:
            return

        old_by_token = self._entry_map(old_entries)
        new_by_token = self._entry_map(new_entries)

        for token in set(old_by_token) - set(new_by_token):
            self.unregister_function_state(parent_scope_id, token)

        for token in set(old_by_token) & set(new_by_token):
            new_value = new_by_token[token]
            scope_id = ScopeKey(parent_scope_id).child(token)
            state = ObjectStateRegistry.get_by_scope(scope_id)
            if state is None:
                continue
            parent_state = ObjectStateRegistry.get_by_scope(parent_scope_id)
            if parent_state is None:
                raise FunctionPatternRoundTripError(
                    f"Missing parent ObjectState for {parent_scope_id!r}."
                )
            self.synchronize_existing_function_state(
                state=state,
                parent_state=parent_state,
                entry=new_value,
            )

    def resolve_pattern_values(
        self,
        *,
        parent_scope_id: str | None,
        pattern: FunctionPatternList | FunctionPatternByKey,
        tokens: PatternTokens,
    ) -> FunctionPatternList | FunctionPatternByKey:
        """Project editable kwargs from materialized child states, including hidden groups.

        Entries without an opened child scope still take their values from the
        declaration. Once materialized, the child ObjectState owns its edits;
        cached pane kwargs are not another value authority.
        """
        if parent_scope_id is None:
            return pattern
        resolved = pattern
        for entry in self.iter_tokenized_entries(pattern, tokens):
            state = ObjectStateRegistry.get_by_scope(ScopeKey(parent_scope_id).child(entry.token))
            if state is None:
                continue
            if not self.same_function_authority(entry.func, state.object_instance):
                raise FunctionPatternRoundTripError(
                    f"Function token {entry.token!r} names a different callable."
                )
            resolved = self._replace_pattern_entry(
                pattern=resolved,
                tokens=tokens,
                token=entry.token,
                next_value=FunctionPatternValue(
                    func=entry.func,
                    kwargs=self.reconstruct_kwargs_from_state(state),
                ),
            )
        return resolved

    @staticmethod
    def _entry_map(
        entries: list[TokenizedFunctionEntry],
    ) -> dict[str, FunctionPatternValue]:
        entry_map: dict[str, FunctionPatternValue] = {}
        for entry in entries:
            if not entry.token:
                continue
            entry_map[entry.token] = FunctionPatternValue(
                entry.func,
                FunctionPatternCodeDocumentService.sanitize_pattern_kwargs(entry.kwargs),
            )
        return entry_map

    @classmethod
    def apply_kwargs_to_state(
        cls,
        *,
        state: ObjectState,
        previous_kwargs: FunctionKwargs,
        next_kwargs: FunctionKwargs,
    ) -> None:
        """Apply kwargs into an existing child ObjectState."""
        for param_name, next_param_value in next_kwargs.items():
            previous_param_value = previous_kwargs.get(param_name)
            if previous_param_value != next_param_value and param_name in state.parameters:
                state.update_parameter(param_name, next_param_value)

        for param_name in previous_kwargs:
            if param_name not in next_kwargs and param_name in state.parameters:
                state.reset_parameter(param_name)

    @staticmethod
    def _editable_callable_surface(func: FunctionAuthority) -> tuple[tuple, frozenset[str]]:
        """Return the parameter surface that an ObjectState can represent."""

        signature = inspect.signature(func)
        return (
            tuple(
                (parameter.name, parameter.kind, parameter.annotation)
                for parameter in signature.parameters.values()
            ),
            parameter_exclusions(func),
        )

    @classmethod
    def synchronize_existing_function_state(
        cls,
        *,
        state: ObjectState,
        parent_state: ObjectState,
        entry: FunctionPatternValue,
    ) -> ObjectState:
        """Synchronize one existing child, replacing it when its form changes."""

        next_callable = EditableFunctionPatternCallable.for_entry(
            entry.func,
            entry.kwargs,
        )
        if not cls.same_function_authority(state.object_instance, entry.func) or (
            cls._editable_callable_surface(state.object_instance)
            != cls._editable_callable_surface(next_callable)
        ):
            cls.replace_function_state(
                scope_id=state.scope_id,
                parent_state=parent_state,
                entry=entry,
            )
            replacement = ObjectStateRegistry.get_by_scope(state.scope_id)
            if replacement is None:
                raise FunctionPatternRoundTripError(
                    f"Function child state {state.scope_id!r} was not replaced."
                )
            return replacement

        cls.apply_kwargs_to_state(
            state=state,
            previous_kwargs=cls.reconstruct_kwargs_from_state(state),
            next_kwargs=entry.kwargs,
        )
        if cls._state_roundtrips_entry(state, entry):
            return state

        # A restored ObjectState can carry the flattened parameter schema from
        # an older declaration even though its callable now resolves to the
        # current function.  Updating a dataclass container cannot safely add
        # or remove fields that the stale state never registered.  Replace the
        # child from the declaration rather than accepting a lossy code-mode
        # application whose rendered source or execution would use defaults.
        cls.replace_function_state(
            scope_id=state.scope_id,
            parent_state=parent_state,
            entry=entry,
        )
        replacement = ObjectStateRegistry.get_by_scope(state.scope_id)
        if replacement is None or not cls._state_roundtrips_entry(replacement, entry):
            raise FunctionPatternRoundTripError(
                f"Function child state {state.scope_id!r} could not preserve its "
                "declared kwargs through ObjectState reconstruction."
            )
        return replacement

    @classmethod
    def _state_roundtrips_entry(
        cls,
        state: ObjectState,
        entry: FunctionPatternValue,
    ) -> bool:
        """Return whether ObjectState preserves the entry's declared kwargs."""

        authority = function_pattern_authority(entry.func)
        expected = callable_declaration_kwargs(
            authority,
            entry.kwargs,
            values_equal=semantic_values_equal,
        )
        reconstructed = callable_declaration_kwargs(
            authority,
            cls.reconstruct_kwargs_from_state(state),
            values_equal=semantic_values_equal,
        )
        return semantic_values_equal(expected, reconstructed)

    @staticmethod
    def unregister_function_state(parent_scope_id: str, token: str) -> None:
        """Unregister one function child ObjectState if it is present."""
        state = ObjectStateRegistry.get_by_scope(ScopeKey(parent_scope_id).child(token))
        if state is not None:
            ObjectStateRegistry.unregister(state, _skip_snapshot=True)

    @classmethod
    def create_function_state(
        cls,
        *,
        scope_id: str,
        parent_state: ObjectState,
        entry: FunctionPatternValue,
    ) -> ObjectState:
        """Construct an unregistered child from its declared function pattern."""
        editable_func = EditableFunctionPatternCallable.for_entry(
            entry.func,
            entry.kwargs,
        )
        return ObjectState(
            object_instance=editable_func,
            scope_id=scope_id,
            parent_state=parent_state,
            exclude_params=cls.reserved_parameter_names(editable_func),
            initial_values=dict(entry.kwargs),
        )

    @classmethod
    def replace_function_state(
        cls,
        *,
        scope_id: str,
        parent_state: ObjectState,
        entry: FunctionPatternValue,
    ) -> None:
        """Replace one child ObjectState while preserving its scope token."""
        current = ObjectStateRegistry.get_by_scope(scope_id)
        if current is not None:
            ObjectStateRegistry.unregister(current, _skip_snapshot=True)
        func_state = cls.create_function_state(
            scope_id=scope_id, parent_state=parent_state, entry=entry
        )
        ObjectStateRegistry.register(func_state, _skip_snapshot=True)

    @staticmethod
    def reserved_parameter_names(func: FunctionAuthority) -> list[str] | None:
        """Return reserved positional input parameter names for a callable."""
        return FunctionPatternParameterExclusions.from_callable(func).as_list()

    @classmethod
    def reconstruct_kwargs_from_state(cls, state: ObjectState) -> FunctionKwargs:
        """Reconstruct top-level kwargs from a flattened ObjectState."""
        return cls.sanitize_pattern_kwargs(state.reconstruct_top_level_parameters())

    def is_function_child_scope(self, scope_id: str) -> bool:
        """Return whether scope_id is a registered function-pattern child scope."""
        try:
            address = FunctionPatternChildScopeAddress.parse(scope_id)
        except FunctionPatternRoundTripError:
            return False

        parent_state = ObjectStateRegistry.get_by_scope(address.parent_scope_id)
        child_state = ObjectStateRegistry.get_by_scope(address.scope_id)
        return (
            parent_state is not None
            and child_state is not None
            and self._parent_state_has_token(parent_state, address.token)
        )

    def child_scope_entry(
        self,
        scope_id: str,
    ) -> FunctionPatternValue:
        """Return the current function-pattern value for a child ObjectState."""
        address = FunctionPatternChildScopeAddress.parse(scope_id)
        parent_state = self.require_parent_state(address)
        child_state = self.require_child_state(address)
        self.require_parent_token(parent_state, address.token)
        if not callable(child_state.object_instance):
            raise FunctionPatternRoundTripError(
                f"Child scope {scope_id!r} does not own a callable value."
            )
        return FunctionPatternValue(
            func=function_pattern_authority(child_state.object_instance),
            kwargs=self.reconstruct_kwargs_from_state(child_state),
        )

    def child_scope_source(self, scope_id: str, *, clean_mode: bool = True) -> str:
        """Render a child function scope as a single-entry pattern document."""
        entry = self.child_scope_entry(scope_id)
        return self.generate_complete_function_pattern_code(
            (entry.func, entry.kwargs),
            clean_mode=clean_mode,
        )

    def child_scope_title(self, scope_id: str) -> str:
        """Return a stable title for a child function scope code document."""
        entry = self.child_scope_entry(scope_id)
        func = entry.func
        try:
            name = func.__name__
        except AttributeError:
            name = type(func).__name__
        return f"Edit Function: {name}"

    def validate_child_scope_source(self, scope_id: str, source: str) -> None:
        """Validate source for one child function scope."""
        self.single_entry_from_source(source)
        self.child_scope_entry(scope_id)

    def apply_child_scope_source(self, scope_id: str, source: str) -> None:
        """Apply a single-entry source document to one function child scope."""
        address = FunctionPatternChildScopeAddress.parse(scope_id)
        parent_state = self.require_parent_state(address)
        self.child_scope_entry(scope_id)
        next_value = self.single_entry_from_source(source)
        self._replace_parent_pattern_entry(
            parent_state=parent_state,
            token=address.token,
            next_value=next_value,
        )

        self.synchronize_existing_function_state(
            state=self.require_child_state(address),
            parent_state=parent_state,
            entry=next_value,
        )

    def single_entry_from_source(self, source: str) -> FunctionPatternValue:
        """Parse a source document that must describe exactly one entry."""
        pattern = self.pattern_from_source(source)
        entry = self._single_pattern_entry(pattern)
        return FunctionPatternValue(func=entry[0], kwargs=entry[1])

    @classmethod
    def _single_pattern_entry(cls, pattern: PatternSourceValue) -> FunctionPatternItem:
        entry = cls.function_and_kwargs(pattern)
        if entry is not None:
            return entry

        if isinstance(pattern, list) and len(pattern) == 1:
            entry = cls.function_and_kwargs(pattern[0])
            if entry is not None:
                return entry

        raise FunctionPatternRoundTripError(
            "Child function scope code documents must assign exactly one "
            "callable or (callable, kwargs) entry to 'pattern'."
        )

    @staticmethod
    def require_parent_state(
        address: FunctionPatternChildScopeAddress,
    ) -> ObjectState:
        """Return the parent ObjectState for a child scope."""
        state = ObjectStateRegistry.get_by_scope(address.parent_scope_id)
        if state is None:
            raise FunctionPatternRoundTripError(
                f"Missing parent ObjectState {address.parent_scope_id!r}."
            )
        return state

    @staticmethod
    def require_child_state(
        address: FunctionPatternChildScopeAddress,
    ) -> ObjectState:
        """Return the child ObjectState for a child scope."""
        state = ObjectStateRegistry.get_by_scope(address.scope_id)
        if state is None:
            raise FunctionPatternRoundTripError(f"Missing child ObjectState {address.scope_id!r}.")
        return state

    def require_parent_token(
        self,
        parent_state: ObjectState,
        token: str,
    ) -> None:
        """Fail loudly when the parent pattern metadata does not own token."""
        if not self._parent_state_has_token(parent_state, token):
            raise FunctionPatternRoundTripError(
                f"Parent scope {parent_state.scope_id!r} does not declare function token {token!r}."
            )

    @staticmethod
    def _parent_state_has_token(parent_state: ObjectState, token: str) -> bool:
        tokens = parent_state.metadata.get(FUNC_EDITOR_PATTERN_TOKENS_META_KEY)
        if isinstance(tokens, list):
            return token in tokens
        if isinstance(tokens, dict):
            return any(token in token_list for token_list in tokens.values())
        return False

    def _replace_parent_pattern_entry(
        self,
        *,
        parent_state: ObjectState,
        token: str,
        next_value: FunctionPatternValue,
    ) -> None:
        pattern_parameter_name = FunctionPatternField.parameter_name()
        if not FunctionPatternField.parameter_in(parent_state.parameters):
            raise FunctionPatternRoundTripError(
                f"Parent scope {parent_state.scope_id!r} has no "
                f"{pattern_parameter_name!r} parameter."
            )
        tokens = parent_state.metadata.get(FUNC_EDITOR_PATTERN_TOKENS_META_KEY)
        next_pattern = self._replace_pattern_entry(
            pattern=FunctionPatternField.value_from(parent_state.parameters),
            tokens=tokens,
            token=token,
            next_value=next_value,
        )
        parent_state.update_parameter(pattern_parameter_name, next_pattern)

    def _replace_pattern_entry(
        self,
        *,
        pattern,
        tokens,
        token: str,
        next_value: FunctionPatternValue,
    ):
        if isinstance(tokens, list):
            index = self._token_index(tokens, token)
            if isinstance(pattern, list):
                if index >= len(pattern):
                    raise FunctionPatternRoundTripError(
                        "Function token metadata is longer than the function pattern."
                    )
                updated = list(pattern)
                updated[index] = self._entry_for_existing_shape(
                    pattern[index],
                    next_value,
                )
                return updated
            if len(tokens) == 1 and index == 0:
                return self._entry_for_existing_shape(pattern, next_value)
            raise FunctionPatternRoundTripError(
                "List token metadata can only address a list pattern or a "
                "single-entry function pattern."
            )

        if isinstance(tokens, dict):
            if not isinstance(pattern, dict):
                raise FunctionPatternRoundTripError(
                    "Dict token metadata requires a dict function pattern."
                )
            for pattern_key, token_list in tokens.items():
                if token not in token_list:
                    continue
                index = self._token_index(token_list, token)
                if pattern_key not in pattern:
                    raise FunctionPatternRoundTripError(
                        f"Function token metadata references missing pattern key {pattern_key!r}."
                    )
                items = pattern[pattern_key]
                if not isinstance(items, list):
                    raise FunctionPatternRoundTripError(
                        "Dict function pattern values must be function lists."
                    )
                if index >= len(items):
                    raise FunctionPatternRoundTripError(
                        "Function token metadata is longer than the keyed pattern."
                    )
                updated_items = list(items)
                updated_items[index] = self._entry_for_existing_shape(
                    items[index],
                    next_value,
                )
                updated_pattern = dict(pattern)
                updated_pattern[pattern_key] = updated_items
                return updated_pattern

        raise FunctionPatternRoundTripError(
            "Function pattern metadata must be a list or dict of child tokens."
        )

    @staticmethod
    def _token_index(tokens: list[str], token: str) -> int:
        if token not in tokens:
            raise FunctionPatternRoundTripError(
                f"Function token {token!r} is not present in parent metadata."
            )
        return tokens.index(token)

    @staticmethod
    def _entry_for_existing_shape(
        existing_entry,
        next_value: FunctionPatternValue,
    ):
        if callable(existing_entry) and not next_value.kwargs:
            return next_value.func
        return next_value.func, next_value.kwargs


class FunctionPatternScopeCodeDocumentDriver(WindowCodeDocumentDriver):
    """WindowCodeDocumentDriver for registered child function ObjectStates."""

    def __init__(
        self,
        scope_id: str,
        service: FunctionPatternCodeDocumentService | None = None,
    ) -> None:
        self._scope_id = scope_id
        self._service = service or FunctionPatternCodeDocumentService()

    @classmethod
    def handles_scope(cls, scope_id: str) -> bool:
        """Return whether this driver can service the requested scope."""
        return FunctionPatternCodeDocumentService().is_function_child_scope(scope_id)

    def read_document(self, clean: bool = True) -> WindowCodeDocument:
        return WindowCodeDocument(
            title=self._service.child_scope_title(self._scope_id),
            source=self._service.child_scope_source(
                self._scope_id,
                clean_mode=clean,
            ),
            mime_type=PYTHON_MIME_TYPE,
            declaration_type=FunctionPatternValue,
        )

    def validate_source(self, source: str) -> None:
        self._service.validate_child_scope_source(self._scope_id, source)

    def apply_source(self, source: str) -> None:
        self._service.apply_child_scope_source(self._scope_id, source)
