"""What an application supplies to the manager widgets it hosts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from typing import Any


class UiHostServices(ABC):
    """Dialogs, background work, the owning window and the colour scheme of the host UI.

    Manager widgets receive one instance and call only these methods.
    """

    main_window: Any
    """The host's main window, which parents dialogs."""

    @abstractmethod
    def get_current_color_scheme(self) -> Any:
        """The toolkit colour scheme widgets paint with."""

    @abstractmethod
    def show_error_dialog(self, error_message: str, title: str = "Error") -> None:
        """Report an error to the user."""

    @abstractmethod
    def show_info_dialog(self, info_message: str, title: str = "Information") -> None:
        """Tell the user something."""

    @abstractmethod
    def execute_async_operation(
        self,
        async_func: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Future:
        """Run one coroutine off the UI thread."""
