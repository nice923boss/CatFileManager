"""Name matching (D02) and the shared search history (D07)."""

import fnmatch
import re
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal


def make_matcher(text: str, regex: bool) -> Callable[[str], bool] | None:
    """Return a name predicate, or None when there is nothing to filter.

    * regex on        -> case-insensitive ``re.search``
    * contains * or ? -> wildcard match on the whole name (``*.jpg``)
    * otherwise       -> case-insensitive substring
    Raises ``re.error`` for an invalid regular expression.
    """
    text = text.strip()
    if not text:
        return None
    if regex:
        pattern = re.compile(text, re.IGNORECASE)
        return lambda name: pattern.search(name) is not None
    if "*" in text or "?" in text:
        pattern = re.compile(fnmatch.translate(text), re.IGNORECASE)
        return lambda name: pattern.match(name) is not None
    low = text.lower()
    return lambda name: low in name.lower()


class SearchHistory(QObject):
    """Most-recent-first list of search texts, shared by every panel."""

    changed = Signal(list)
    LIMIT = 20

    def __init__(self):
        super().__init__()
        self._items: list[str] = []

    def load(self, items: list) -> None:
        self._items = [str(i) for i in items if str(i).strip()][: self.LIMIT]

    def items(self) -> list[str]:
        return list(self._items)

    def add(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self._items = [text, *[i for i in self._items if i != text]][: self.LIMIT]
        self.changed.emit(self.items())

    def remove(self, text: str) -> None:
        self._items = [i for i in self._items if i != text]
        self.changed.emit(self.items())

    def clear(self) -> None:
        self._items = []
        self.changed.emit([])


search_history = SearchHistory()
