"""Generic operation kinds: identity and exclusivity for every UI backend.

A kind of work declares its identity (class name, derived once) and whether
a newer start cancels a running one (exclusive). Native operation owners
start, cancel and wait through their own toolkit; the kind is the authority
for which group that work belongs to.

Moved from Toad's ``toad.worker_group.WorkerGroup`` with native Textual
Worker/DOMNode/work removed.
"""

from __future__ import annotations

from typing import ClassVar


class ExclusiveKind:
    """Capability mixin: a newer start of this kind cancels the running one."""


class OperationKind:
    """One kind of asynchronous work, identified by its class.

    Each concrete kind is an empty class whose meaning is its base list:
    ``class ThreadInterestUpdate(OperationKind, ExclusiveKind): ...``

    Identity is the class itself. The group name is derived once from the
    module-qualified class name in ``__init_subclass__``, so no member
    writes a string. Exclusivity is declared by inheriting ``ExclusiveKind``.
    """

    group: ClassVar[str]
    exclusive: ClassVar[bool] = False

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        cls.group = f"{cls.__module__}.{cls.__qualname__}"
        cls.exclusive = issubclass(cls, ExclusiveKind)
