"""
Helpers for generating stable scope tokens for ObjectState hierarchy nodes.

Used to avoid cross-window collisions when multiple child editors share the
same scope prefix (e.g., steps, nested functions).
"""

from __future__ import annotations

import logging
from abc import ABC
from collections.abc import Callable, Iterable, Sequence
from typing import Optional, TypeVar

from objectstate import semantic_values_equal
from objectstate import ScopeKey

logger = logging.getLogger(__name__)

Occurrence = TypeVar("Occurrence")


def reconcile_occurrence_tokens(
    previous_occurrences: Sequence[Occurrence],
    previous_tokens: Sequence[str],
    next_occurrences: Sequence[Occurrence],
    *,
    same_declaration: Callable[[Occurrence, Occurrence], bool],
    occurrence_authorities: Callable[[Occurrence], Sequence[object]],
    token_factory: Callable[[], str],
    requested_tokens: Sequence[str | None] | None = None,
    claimed_tokens: set[str] | None = None,
) -> list[str]:
    """Reconcile occurrence identity without treating list position as authority.

    Existing explicit tokens are authoritative. Tokenless declarations first match
    exact prior declarations, then match a changed declaration only when the
    authority relation is unambiguous in both directions. Every remaining
    declaration receives a fresh token.
    """

    requested = requested_tokens or ()
    claimed = claimed_tokens if claimed_tokens is not None else set()
    available = {
        index
        for index, token in enumerate(previous_tokens[: len(previous_occurrences)])
        if token and token not in claimed
    }
    token_to_previous = {
        str(previous_tokens[index]): index
        for index in available
    }
    previous_token_set = {
        str(token) for token in previous_tokens[: len(previous_occurrences)] if token
    }
    resolved: list[str | None] = [None] * len(next_occurrences)

    for next_index, requested_token in enumerate(requested):
        if next_index >= len(resolved) or not requested_token:
            continue
        token = str(requested_token)
        if token in claimed:
            continue
        previous_index = token_to_previous.get(token)
        if previous_index in available:
            available.remove(previous_index)
        elif token in previous_token_set:
            continue
        resolved[next_index] = token
        claimed.add(token)

    for next_index, next_occurrence in enumerate(next_occurrences):
        if resolved[next_index] is not None:
            continue
        previous_index = next(
            (
                candidate
                for candidate in sorted(available)
                if same_declaration(
                    previous_occurrences[candidate],
                    next_occurrence,
                )
            ),
            None,
        )
        if previous_index is None:
            continue
        token = str(previous_tokens[previous_index])
        resolved[next_index] = token
        available.remove(previous_index)
        claimed.add(token)

    unresolved_next = {
        index for index, token in enumerate(resolved) if token is None
    }
    previous_authorities = [
        tuple(occurrence_authorities(value)) for value in previous_occurrences
    ]
    next_authorities = [
        tuple(occurrence_authorities(value)) for value in next_occurrences
    ]
    authority_level_count = max(
        (len(authorities) for authorities in previous_authorities + next_authorities),
        default=0,
    )
    for authority_level in range(authority_level_count):
        unresolved_next = {
            index for index, token in enumerate(resolved) if token is None
        }
        authority_candidates = {
            next_index: {
                previous_index
                for previous_index in available
                if authority_level < len(previous_authorities[previous_index])
                and authority_level < len(next_authorities[next_index])
                and semantic_values_equal(
                    previous_authorities[previous_index][authority_level],
                    next_authorities[next_index][authority_level],
                )
            }
            for next_index in unresolved_next
        }
        for next_index in sorted(unresolved_next):
            candidates = authority_candidates[next_index] & available
            if len(candidates) != 1:
                continue
            previous_index = next(iter(candidates))
            competing_next = {
                candidate
                for candidate in unresolved_next
                if resolved[candidate] is None
                and previous_index in authority_candidates[candidate]
            }
            if len(competing_next) != 1:
                continue
            token = str(previous_tokens[previous_index])
            resolved[next_index] = token
            available.remove(previous_index)
            claimed.add(token)

    for index, token in enumerate(resolved):
        if token is not None:
            continue
        fresh_token = token_factory()
        while fresh_token in claimed:
            fresh_token = token_factory()
        resolved[index] = fresh_token
        claimed.add(fresh_token)

    return [str(token) for token in resolved]


class ScopeTokenTarget(ABC):
    """Nominal role for objects that can participate in scope-token identity."""


class ScopeTokenObjectStore:
    """Persist scope tokens without exposing attribute probing to callers."""

    @classmethod
    def read(cls, obj: ScopeTokenTarget, attr_name: str) -> Optional[str]:
        attributes = cls._instance_attributes(obj)
        if attributes is not None and attr_name in attributes:
            token = attributes[attr_name]
            if isinstance(token, str) and token:
                return token
        return None

    @classmethod
    def write(cls, obj: ScopeTokenTarget, attr_name: str, token: str) -> None:
        attributes = cls._instance_attributes(obj)
        attributes[attr_name] = token

    @staticmethod
    def _instance_attributes(obj: ScopeTokenTarget):
        try:
            return vars(obj)
        except TypeError as exc:
            raise TypeError(
                "Scope-token targets must expose an instance attribute mapping."
            ) from exc


class ScopeTokenGenerator:
    """Generate unique, human-readable scope tokens with an optional attribute store.

    - If attr_name is provided and the target object exposes an instance mapping,
      tokens are persisted there (e.g., FunctionStep._scope_token).
    - Tracks seen tokens to avoid collisions when objects already carry tokens
      (e.g., after deserialization).
    """

    def __init__(self, prefix: str, attr_name: Optional[str] = None):
        self.prefix = prefix
        self.attr_name = attr_name
        self._counter: int = 0
        self._used_tokens: set[str] = set()

    # ---------- Seeding ----------
    def seed_from_tokens(self, tokens: Iterable[str] | None) -> None:
        """Prime the generator with existing tokens (keeps counter ahead of them)."""
        if tokens is None:
            return
        for token in tokens:
            if not token:
                continue
            self._register_existing(token)

    def seed_from_objects(
        self,
        objects: Iterable[ScopeTokenTarget] | None,
    ) -> None:
        """Seed from objects that may already carry tokens on attr_name."""
        if not self.attr_name:
            return
        if objects is None:
            return
        for obj in objects:
            token = self._get_existing(obj)
            if token:
                self._register_existing(token)

    # ---------- Public API ----------
    def ensure(self, obj: Optional[ScopeTokenTarget] = None) -> str:
        """Return an existing token on obj or generate a new one."""
        existing = self._get_existing(obj)
        if existing:
            self._register_existing(existing)
            return existing

        token = self._generate_new()
        self._attach(obj, token)
        return token

    def transfer(self, source: ScopeTokenTarget, target: ScopeTokenTarget) -> str:
        """Copy source token to target (or generate a new one for target)."""
        token = self._get_existing(source)
        if not token:
            token = self.ensure(target)
            return token

        self._register_existing(token)
        self._attach(target, token)
        return token

    def normalize(self, objects: Iterable[ScopeTokenTarget] | None) -> None:
        """Ensure every object in a list has a token."""
        if objects is None:
            return
        for obj in objects:
            self.ensure(obj)

    # ---------- Internals ----------
    def _get_existing(self, obj: Optional[ScopeTokenTarget]) -> Optional[str]:
        if obj is None or not self.attr_name:
            return None
        token = self.existing_token(obj, self.attr_name)
        return token

    @staticmethod
    def existing_token(obj: ScopeTokenTarget, attr_name: str) -> Optional[str]:
        """Return an existing token from the configured storage attribute."""
        return ScopeTokenObjectStore.read(obj, attr_name)

    def _attach(self, obj: Optional[ScopeTokenTarget], token: str) -> None:
        if obj is None or not self.attr_name:
            return
        ScopeTokenObjectStore.write(obj, self.attr_name, token)

    def _register_existing(self, token: str) -> None:
        if token in self._used_tokens:
            return
        self._used_tokens.add(token)
        self._bump_counter(token)

    def _bump_counter(self, token: str) -> None:
        prefix = f"{self.prefix}_"
        if token.startswith(prefix):
            suffix = token[len(prefix) :]
            if suffix.isdigit():
                self._counter = max(self._counter, int(suffix) + 1)

    def _generate_new(self) -> str:
        token = f"{self.prefix}_{self._counter}"
        while token in self._used_tokens:
            self._counter += 1
            token = f"{self.prefix}_{self._counter}"
        self._used_tokens.add(token)
        self._counter += 1
        return token


class ScopeTokenService:
    """Registry of ScopeTokenGenerators keyed by (parent_scope, prefix).

    Token assigned on creation, stable across reordering.
    Prefix derived from object type for readability.

    Usage:
        ScopeTokenService.build_scope_id(plate_path, step)   # → "plate::step_0"
        ScopeTokenService.build_scope_id(step_scope, func)   # → "plate::step_0::func_0"
    """
    SCOPE_TOKEN_ATTRIBUTE = "_scope_token"
    _generators: dict[tuple[str, str], ScopeTokenGenerator] = {}

    @classmethod
    def _get_prefix(cls, obj: ScopeTokenTarget) -> str:
        """Derive prefix from object type (lowercase)."""
        return type(obj).__name__.lower()

    @classmethod
    def _normalize_scope(cls, scope) -> str:
        """Normalize scope to string. Enforces the invariant: scope keys are always strings."""
        if scope is None:
            return ""
        return str(scope)

    @classmethod
    def get_generator(cls, parent_scope, prefix: str) -> ScopeTokenGenerator:
        parent_scope = cls._normalize_scope(parent_scope)
        key = (parent_scope, prefix)
        if key not in cls._generators:
            cls._generators[key] = ScopeTokenGenerator(prefix, cls.SCOPE_TOKEN_ATTRIBUTE)
            logger.debug(f"🔑 ScopeTokenService: Created generator for parent_scope={parent_scope}, prefix={prefix}")
        return cls._generators[key]

    @classmethod
    def ensure_token(cls, parent_scope, obj: ScopeTokenTarget) -> str:
        parent_scope = cls._normalize_scope(parent_scope)
        prefix = cls._get_prefix(obj)
        return cls.get_generator(parent_scope, prefix).ensure(obj)

    @classmethod
    def transfer_token(
        cls,
        parent_scope,
        source: ScopeTokenTarget,
        target: ScopeTokenTarget,
    ) -> str:
        """Transfer source object's scope token to a replacement target."""
        parent_scope = cls._normalize_scope(parent_scope)
        prefix = cls._get_prefix(source)
        token = cls.get_generator(parent_scope, prefix).transfer(source, target)
        cls._scope_id_cache.pop((parent_scope, id(target)), None)
        return token

    @classmethod
    def adopt_token(
        cls,
        parent_scope,
        obj: ScopeTokenTarget,
        token: str,
    ) -> str:
        """Assign a known scope token to an object through the token authority."""
        cls.restore_object_token(obj, token)
        parent_scope = cls._normalize_scope(parent_scope)
        prefix = cls._get_prefix(obj)
        generator = cls.get_generator(parent_scope, prefix)
        generator.seed_from_tokens((token,))
        cls._scope_id_cache.pop((parent_scope, id(obj)), None)
        return token

    @classmethod
    def restore_object_token(cls, obj: ScopeTokenTarget, token: str) -> str:
        """Restore detached object identity without registering it in a scope.

        Deserialization/validation can prepare an object without changing any
        live generator counter, used-token set or scope-ID cache. Ordinary
        later build/seed/adopt operations perform their explicit registration.
        """
        ScopeTokenObjectStore.write(obj, cls.SCOPE_TOKEN_ATTRIBUTE, token)
        return token

    @classmethod
    def object_token(cls, obj: ScopeTokenTarget) -> str | None:
        """Return an object's existing scope token without creating one."""
        return ScopeTokenObjectStore.read(obj, cls.SCOPE_TOKEN_ATTRIBUTE)

    @classmethod
    def same_object_token(
        cls,
        left: ScopeTokenTarget,
        right: ScopeTokenTarget,
    ) -> bool:
        """Return whether two objects carry the same existing scope token."""
        left_token = cls.object_token(left)
        if left_token is None:
            return False
        return left_token == cls.object_token(right)

    # PERFORMANCE: Cache scope_id strings per (parent_scope, object_id)
    _scope_id_cache: dict[tuple[str, int], str] = {}

    @staticmethod
    def _scope_id_for_token(parent_scope: str, token: str) -> ScopeKey:
        """The one serialization projection of nominal object-token identity."""
        return ScopeKey(parent_scope).child(token)

    @classmethod
    def build_scope_id(cls, parent_scope, obj: ScopeTokenTarget) -> str:
        parent_scope = cls._normalize_scope(parent_scope)
        # Python can reuse a departed object's numeric ID. The cache is only a
        # projection; the current object's declaration-owned token remains the
        # identity authority, even when a numeric cache key happens to match.
        cache_key = (parent_scope, id(obj))
        cached = cls._scope_id_cache.get(cache_key)
        existing_token = cls.object_token(obj)
        if (cached is not None and existing_token is not None
                and cached == cls._scope_id_for_token(parent_scope, existing_token)):
            return cached

        token = cls.ensure_token(parent_scope, obj)
        result = cls._scope_id_for_token(parent_scope, token)
        cls._scope_id_cache[cache_key] = result
        logger.debug(f"🔑 ScopeTokenService.build_scope_id: {result} for {type(obj).__name__}")
        return result

    @classmethod
    def seed_from_objects(
        cls,
        parent_scope,
        objects: Sequence[ScopeTokenTarget],
    ) -> None:
        """Seed generators from existing objects (preserves their tokens)."""
        if not objects:
            return
        parent_scope = cls._normalize_scope(parent_scope)
        # Group by type prefix
        by_prefix: dict[str, list[ScopeTokenTarget]] = {}
        for obj in objects:
            prefix = cls._get_prefix(obj)
            if prefix not in by_prefix:
                by_prefix[prefix] = []
            by_prefix[prefix].append(obj)
        # Seed each generator
        for prefix, objs in by_prefix.items():
            cls.get_generator(parent_scope, prefix).seed_from_objects(objs)

    @classmethod
    def clear_scope(cls, parent_scope) -> None:
        """Clear all generators for a parent scope (and nested children)."""
        parent_scope = cls._normalize_scope(parent_scope)
        keys_to_remove = [k for k in cls._generators if ScopeKey(parent_scope).contains(k[0])]
        for key in keys_to_remove:
            del cls._generators[key]

        # PERFORMANCE: Also clear scope_id cache for this scope
        cache_keys_to_remove = [
            k for k in cls._scope_id_cache if ScopeKey(parent_scope).contains(k[0])
        ]
        for key in cache_keys_to_remove:
            del cls._scope_id_cache[key]

        if keys_to_remove:
            logger.debug(f"🔑 ScopeTokenService: Cleared {len(keys_to_remove)} generators for {parent_scope}")
