"""
Service registry loader for the Control Plane.

The registry is the repo UNIVERSE the Impact Analyzer may search. It holds
repo identity only — stream, stack, contract path. It does NOT hold the branch
to analyze: that comes from the story input per run (target_branch), so
parallel releases can run at once and the registry changes only when a repo is
added or removed.

Stream filtering: a PM story searches only PM repos; a VoC story only VoC repos.

Stdlib + PyYAML only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml


@dataclass
class RepoEntry:
    name: str
    stream: str
    stack: str
    contract_path: str
    raw: dict = field(default_factory=dict)


class ServiceRegistry:
    def __init__(self, defaults: dict, repos: dict[str, dict]):
        self._defaults = defaults or {}
        self._repos_raw = repos or {}

    # ---- loading -----------------------------------------------------
    @classmethod
    def load(cls, path: str) -> "ServiceRegistry":
        if not os.path.exists(path):
            raise FileNotFoundError(f"service registry not found: {path}")
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls(defaults=data.get("defaults", {}), repos=data.get("repos", {}))

    # ---- resolution --------------------------------------------------
    def _resolve_contract_path(self, name: str, entry: dict) -> str:
        template = (
            entry.get("contract_path")
            or self._defaults.get("contract_path")
            or "api/{service}.yaml"
        )
        return template.replace("{service}", name)

    def get(self, name: str) -> RepoEntry:
        if name not in self._repos_raw:
            raise KeyError(f"repo not in registry: {name}")
        entry = self._repos_raw[name] or {}
        return RepoEntry(
            name=name,
            stream=entry.get("stream", ""),
            stack=entry.get("stack", "backend"),
            contract_path=self._resolve_contract_path(name, entry),
            raw=entry,
        )

    def all(self, stream: str | None = None) -> list[RepoEntry]:
        """All repos, optionally filtered to a stream (PM | VoC)."""
        entries = [self.get(name) for name in self._repos_raw]
        if stream:
            s = stream.strip().lower()
            entries = [e for e in entries if e.stream.lower() == s]
        return entries

    def names(self, stream: str | None = None) -> list[str]:
        return [e.name for e in self.all(stream)]

    def contains(self, name: str) -> bool:
        return name in self._repos_raw


if __name__ == "__main__":
    import sys
    reg = ServiceRegistry.load(sys.argv[1] if len(sys.argv) > 1
                               else "config/service-registry.yaml")
    stream = sys.argv[2] if len(sys.argv) > 2 else None
    for r in reg.all(stream):
        print(f"{r.name:20} stream={r.stream:4} stack={r.stack:16} "
              f"contract={r.contract_path}")
