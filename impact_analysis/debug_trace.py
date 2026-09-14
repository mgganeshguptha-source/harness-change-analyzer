"""
debug_trace.py — optional per-stage debug trace for the analyzer.

Toggled per story via `debug: true` in analysis_target_branch.yaml. When on, it
writes a human-readable trace of every pipeline stage to BOTH:
  * the console (stderr — shows in the GitHub Actions log), and
  * a file (change-sets/<story>.debug.log) — committed with the other artifacts.

Verbose mode includes extracted terms, change-type scores, shortlist scores,
code-signal evidence, and the FULL LLM prompt and response — so anyone can see
exactly how a result was produced. When off, nothing is emitted (zero overhead).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone


class DebugTracer:
    def __init__(self, enabled: bool = False, file_path: str | None = None):
        self.enabled = enabled
        self.file_path = file_path
        self._fh = None
        if self.enabled and self.file_path:
            try:
                self._fh = open(self.file_path, "w", encoding="utf-8")
            except Exception:  # noqa: BLE001
                self._fh = None

    def _ts(self) -> str:
        return datetime.now(timezone.utc).strftime("%H:%M:%S")

    def _emit(self, text: str) -> None:
        if not self.enabled:
            return
        print(text, file=sys.stderr, flush=True)
        if self._fh:
            self._fh.write(text + "\n")
            self._fh.flush()

    def stage(self, name: str) -> None:
        self._emit(f"\n{'='*70}\n[{self._ts()}] STAGE: {name}\n{'='*70}")

    def line(self, label: str, value="") -> None:
        self._emit(f"  {label}: {value}" if value != "" else f"  {label}")

    def block(self, label: str, content: str) -> None:
        self._emit(f"  {label}:\n{'-'*70}\n{content}\n{'-'*70}")

    def kv(self, label: str, mapping: dict) -> None:
        self._emit(f"  {label}:")
        for k, v in (mapping or {}).items():
            self._emit(f"      {k} = {v}")

    def list_(self, label: str, items: list) -> None:
        self._emit(f"  {label}: ({len(items or [])})")
        for it in (items or []):
            self._emit(f"      - {it}")

    def close(self) -> None:
        if self._fh:
            try:
                self._fh.close()
            except Exception:  # noqa: BLE001
                pass
            self._fh = None
