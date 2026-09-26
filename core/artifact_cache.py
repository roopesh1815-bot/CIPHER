"""Small file-backed cache that reloads when an artifact changes on disk."""

from pathlib import Path
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class FileArtifactCache(Generic[T]):
    def __init__(self) -> None:
        self._signature: tuple[int, int, int] | None = None
        self._value: T | None = None

    def load(self, path: Path, loader: Callable[[Path], T]) -> T:
        try:
            stat = path.stat()
        except FileNotFoundError:
            self._signature = None
            self._value = None
            raise

        signature = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        if self._value is None or signature != self._signature:
            value = loader(path)
            self._value = value
            self._signature = signature
        assert self._value is not None
        return self._value
