"""Nominal manager workflow capabilities for AbstractManagerWidget."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from metaclass_registry import AutoRegisterMeta


class ManagerCodeExecutionWorkflow(ABC, metaclass=AutoRegisterMeta):
    """Workflow that applies code-editor namespaces to manager state."""

    __registry_key__ = "workflow_key"
    __skip_if_no_key__ = True

    @abstractmethod
    def migration_namespace(
        self,
        code: str,
        error: Exception,
    ) -> Optional[dict]:
        raise NotImplementedError

    @abstractmethod
    def apply_namespace(self, namespace: dict) -> bool:
        raise NotImplementedError

    @abstractmethod
    def validate_namespace(self, namespace: dict) -> bool:
        raise NotImplementedError


class NullManagerCodeExecutionWorkflow(ManagerCodeExecutionWorkflow):
    """Default code execution workflow for managers without code-edit support."""

    workflow_key = "null"

    def migration_namespace(
        self,
        code: str,
        error: Exception,
    ) -> Optional[dict]:
        del code, error
        return None

    def apply_namespace(self, namespace: dict) -> bool:
        del namespace
        return False

    def validate_namespace(self, namespace: dict) -> bool:
        del namespace
        return False


class ManagerDeletionWorkflow(ABC, metaclass=AutoRegisterMeta):
    """Workflow that validates and deletes selected manager items."""

    __registry_key__ = "workflow_key"
    __skip_if_no_key__ = True

    @abstractmethod
    def validate(self, items: list[Any]) -> bool:
        raise NotImplementedError

    @abstractmethod
    def delete(self, items: list[Any]) -> None:
        raise NotImplementedError


class NullManagerDeletionWorkflow(ManagerDeletionWorkflow):
    """Default deletion workflow for managers that must provide deletion logic."""

    workflow_key = "null"

    def validate(self, items: list[Any]) -> bool:
        del items
        return True

    def delete(self, items: list[Any]) -> None:
        del items
        raise NotImplementedError("Manager deletion workflow is not configured")
