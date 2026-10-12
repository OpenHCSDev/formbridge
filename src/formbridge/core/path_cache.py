"""Last-used directories remembered per dialog context across sessions.

A context is a :class:`PathCacheKey` subclass. The family is open: applications
declare their own contexts by subclassing, and each context's key in the cache
file is derived from its class name.
"""

import json
import logging
import re
from pathlib import Path

from metaclass_registry import AutoRegisterMeta

logger = logging.getLogger(__name__)


def _stored_key(name: str, cls: type) -> str | None:
    if "__registry__" in vars(cls):
        return None
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class PathCacheKey(metaclass=AutoRegisterMeta):
    """A dialog context whose last-used directory is remembered.

    Subclass to declare a context; ``stored_key`` is the snake_case class name.
    """

    __registry_key__ = "stored_key"
    __key_extractor__ = _stored_key
    __skip_if_no_key__ = True

    stored_key: str


class General(PathCacheKey):
    """A path parameter whose name declares no file or directory role."""


class FileSelection(PathCacheKey):
    """A file chosen for a file-valued parameter."""


class DirectorySelection(PathCacheKey):
    """A directory chosen for a directory-valued parameter."""


class CodeEditor(PathCacheKey):
    """A Python file loaded into or saved from the code editor."""


class UnifiedPathCache:
    """JSON file mapping each context's ``stored_key`` to its last directory."""

    def __init__(self, cache_file: Path | None = None):
        if cache_file is None:
            from formbridge.protocols.form_config import get_form_config

            config = get_form_config()
            if config.path_cache_file:
                cache_file = Path(config.path_cache_file)
            else:
                cache_file = Path.home() / ".cache" / "formbridge" / "path_cache.json"

        self.cache_file = cache_file
        self._cache: dict[str, str] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        try:
            if self.cache_file.exists():
                with open(self.cache_file) as f:
                    self._cache = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load path cache: {e}")
            self._cache = {}

    def _save_cache(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, "w") as f:
                json.dump(self._cache, f, indent=2)
        except OSError as e:
            logger.warning(f"Failed to save path cache: {e}")

    def get_cached_path(self, key: type[PathCacheKey]) -> Path | None:
        """Return the remembered directory for ``key`` if it still exists."""

        cached_str = self._cache.get(key.stored_key)
        if not cached_str:
            return None
        cached_path = Path(cached_str)
        if cached_path.exists():
            return cached_path
        del self._cache[key.stored_key]
        self._save_cache()
        return None

    def set_cached_path(self, key: type[PathCacheKey], path: Path) -> None:
        """Remember ``path`` for ``key``; a path that does not exist is ignored."""

        if path and path.exists():
            self._cache[key.stored_key] = str(path)
            self._save_cache()
        else:
            logger.warning(f"Attempted to cache non-existent path for {key.stored_key}: {path}")

    def get_initial_path(self, key: type[PathCacheKey], fallback: Path | None = None) -> Path:
        """Return the remembered directory, else ``fallback``, else the home directory."""

        cached = self.get_cached_path(key)
        if cached:
            return cached
        if fallback and fallback.exists():
            return fallback
        return Path.home()


_global_path_cache: UnifiedPathCache | None = None


def get_path_cache() -> UnifiedPathCache:
    """Return the process-wide path cache."""

    global _global_path_cache
    if _global_path_cache is None:
        _global_path_cache = UnifiedPathCache()
    return _global_path_cache


def cache_path(key: type[PathCacheKey], path: Path) -> None:
    """Remember ``path`` for ``key`` in the process-wide cache."""

    get_path_cache().set_cached_path(key, path)


def get_initial_path(key: type[PathCacheKey], fallback: Path | None = None) -> Path:
    """Return the starting directory for a dialog opened in context ``key``."""

    return get_path_cache().get_initial_path(key, fallback)
