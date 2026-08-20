"""State handling for ``hreg watch``: report only announcements / search hits
that were not seen on a previous run.

First contact with a feed (fresh state file, or a search query watched for the
first time) *seeds* the state silently — otherwise every cron setup would fire
hundreds of stale notifications on its first run.
"""
from __future__ import annotations

import json
from pathlib import Path


class WatchState:
    def __init__(self, path):
        self.path = Path(path)
        self._seen_ann: set = set()
        self._seen_search: dict = {}
        self._loaded = False
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._seen_ann = set(data.get("announcements", []))
            self._seen_search = {q: set(keys) for q, keys in data.get("searches", {}).items()}
            self._loaded = True

    def new_announcements(self, anns: list) -> list:
        """Return announcements not seen before; marks all of them as seen."""
        seeding = not self._loaded
        fresh = [a for a in anns if a.id not in self._seen_ann]
        self._seen_ann.update(a.id for a in anns)
        return [] if seeding else fresh

    def new_search_hits(self, query: str, hits: list) -> list:
        """Diff search results for *query*; ``hits`` are (key, payload) tuples.

        A query watched for the first time only seeds its seen-set.
        """
        seeding = query not in self._seen_search
        seen = self._seen_search.setdefault(query, set())
        fresh = [(key, payload) for key, payload in hits if key not in seen]
        seen.update(key for key, _ in hits)
        return [] if seeding else fresh

    def save(self) -> None:
        data = {
            "announcements": sorted(self._seen_ann),
            "searches": {q: sorted(keys) for q, keys in self._seen_search.items()},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
