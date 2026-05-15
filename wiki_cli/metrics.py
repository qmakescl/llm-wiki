"""Tiny metrics collector used by ops and tests."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Metrics:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.counters: dict[str, int] = {}
        self.values: dict[str, list[float | int | str]] = {}
        self.timings: dict[str, float] = {}

    def count(self, name: str, amount: int = 1) -> None:
        if not self.enabled:
            return
        self.counters[name] = self.counters.get(name, 0) + amount

    def record(self, name: str, value: float | int | str) -> None:
        if not self.enabled:
            return
        self.values.setdefault(name, []).append(value)

    @contextmanager
    def timer(self, name: str) -> Iterator[None]:
        if not self.enabled:
            yield
            return
        start = time.perf_counter()
        try:
            yield
        finally:
            self.timings[name] = self.timings.get(name, 0.0) + (time.perf_counter() - start)

    def summary(self) -> dict:
        return {
            "counters": dict(self.counters),
            "values": dict(self.values),
            "timings": dict(self.timings),
        }

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.summary(), indent=2, ensure_ascii=False), encoding="utf-8")


DISABLED = Metrics(enabled=False)
