"""
Service registry loader for harness-change-analyzer.

The registry is the repo UNIVERSE the analyzer may search. Repo identity only —
stack and contract paths. No branch (target_branch comes from the story) and no
team/stream tag (removed: capabilities are derived from contracts, not tagged).

A repo may declare MULTIPLE contract paths/globs (contract_paths). All matching
files are read at run time (recall-first).

Stdlib + PyYAML only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml


@dataclass
class RepoEntry:
    name: str
    stack: str
    contract_paths: list          # exact paths and/or globs, e.g. ["api/*.yaml"]
    raw: dict = field(default_factory=dict)


class ServiceRegistry:
    def __init__(self, defaults: dict, repos: dict[str, dict]):
        self._defaults = defaults or {}
        self._repos_raw = repos or {}

    @classmethod
    def load(cls, path: str) -> "ServiceRegistry":
        if not os.path.exists(path):
            raise FileNotFoundError(f"service registry not found: {path}")
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls(defaults=data.get("defaults", {}), repos=data.get("repos", {}))

    def _resolve_contract_paths(self, name: str, entry: dict) -> list:
        paths = entry.get("contract_paths")
        if paths:
            return paths if isinstance(paths, list) else [paths]
        dflt = self._defaults.get("contract_paths", ["api/*.yaml"])
        return dflt if isinstance(dflt, list) else [dflt]

    def get(self, name: str) -> RepoEntry:
        if name not in self._repos_raw:
            raise KeyError(f"repo not in registry: {name}")
        entry = self._repos_raw[name] or {}
        return RepoEntry(
            name=name,
            stack=entry.get("stack", "backend"),
            contract_paths=self._resolve_contract_paths(name, entry),
            raw=entry,
        )

    def all(self) -> list[RepoEntry]:
        return [self.get(name) for name in self._repos_raw]

    def names(self) -> list[str]:
        return list(self._repos_raw.keys())

    def contains(self, name: str) -> bool:
        return name in self._repos_raw


if __name__ == "__main__":
    import sys
    reg = ServiceRegistry.load(sys.argv[1] if len(sys.argv) > 1
                               else "config/service-registry.yaml")
    for r in reg.all():
        print(f"{r.name:20} stack={r.stack:16} contracts={r.contract_paths}")
