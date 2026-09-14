"""
code_signals.py — deeper cross-repo evidence via shallow clone + grep.

Contract reading (repo_reader) tells us the SHAPE of each service's API. This
module adds CODE-LEVEL evidence of how consumers actually call providers, which
catches couplings a contract diff alone misses:

  * WebClient call paths   — .uri("/pricing/{id}") matched to a provider path
  * DTO / schema usage      — references to a provider's schema names in code
  * config base-URLs        — properties pointing at a downstream service

Each detected signal carries EVIDENCE: the consumer repo, what matched, the
file, the line, and the commit SHA of the analysis branch — so human review is
meaningful and later accuracy measurement has data.

Access method: shallow clone each candidate repo at its analysis branch and grep
locally. This works at ANY branch (release/dev branches, not just default) and
is more reliable than the code-search API. Slower, but candidates are already
narrowed by the lexical shortlist, so the set is small.

WebClient-only for now (Spring WebFlux). RestTemplate/Feign can be added to
CALL_PATTERNS later once the dev team confirms usage.

Stdlib only (git via subprocess, regex).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field

# --- what we grep for -------------------------------------------------
# Inter-service HTTP call mechanisms. WebClient today; extend later.
CALL_PATTERNS = [
    # WebClient fluent calls that carry a URI
    re.compile(r'\.uri\(\s*["\']([^"\']+)["\']'),          # .uri("/pricing/{id}")
    re.compile(r'\.(?:get|post|put|delete|patch)\(\)'),    # .get() etc (weak signal)
]
# config properties pointing at a downstream service base URL
CONFIG_URL_PATTERN = re.compile(
    r'^([\w.\-]*(?:url|uri|host|endpoint|base-?url)[\w.\-]*)\s*[:=]\s*(\S+)',
    re.IGNORECASE)

# file types worth scanning
CODE_EXTS = {".java", ".kt", ".yaml", ".yml", ".properties", ".ts"}

CLONE_TIMEOUT = 120


@dataclass
class Signal:
    kind: str            # "webclient_call" | "dto_usage" | "config_url"
    matched: str         # the path/schema/property that matched
    file: str            # path within the repo
    line: int
    provider: str = ""   # provider repo this signal points to (if resolved)


@dataclass
class CodeScan:
    repo: str
    ref: str
    commit_sha: str = ""
    signals: list = field(default_factory=list)   # list[Signal]
    errors: list = field(default_factory=list)

    def edges_to(self, provider: str) -> list:
        return [s for s in self.signals if s.provider == provider]


def _run(cmd, cwd=None, timeout=CLONE_TIMEOUT):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout)


class CodeSignalScanner:
    def __init__(self, owner: str, token: str | None = None):
        self.owner = owner
        self.token = token or os.environ.get("GITHUB_TOKEN")

    def _clone_url(self, repo: str) -> str:
        if self.token:
            return f"https://x-access-token:{self.token}@github.com/{self.owner}/{repo}.git"
        return f"https://github.com/{self.owner}/{repo}.git"

    def _shallow_clone(self, repo: str, ref: str, dest: str) -> str | None:
        """Clone one repo at ref, depth 1. Returns commit SHA or None on failure."""
        r = _run(["git", "clone", "--depth", "1", "--branch", ref,
                  self._clone_url(repo), dest])
        if r.returncode != 0:
            return None
        rev = _run(["git", "rev-parse", "HEAD"], cwd=dest)
        return rev.stdout.strip() if rev.returncode == 0 else ""

    # ---- provider index: paths + schema names to match against ------
    @staticmethod
    def build_provider_index(snapshots: list) -> dict:
        """
        From contract snapshots, build a lookup used to attribute a consumer
        signal to a provider:
          { provider_repo: {"paths": set[str], "schemas": set[str]} }
        Paths are normalised to their static prefix (before the first {param}).
        """
        idx = {}
        for snap in snapshots:
            paths, schemas = set(), set()
            for c in snap.contracts:
                import yaml
                try:
                    doc = yaml.safe_load(c.text)
                except Exception:  # noqa: BLE001
                    doc = None
                if isinstance(doc, dict):
                    for p in (doc.get("paths") or {}):
                        paths.add(p)
                    comps = (doc.get("components") or {}).get("schemas") or {}
                    schemas.update(comps.keys())
            idx[snap.name] = {"paths": paths, "schemas": schemas}
        return idx


    @staticmethod
    def _path_prefix(path: str) -> str:
        # "/pricing/{bookId}" -> "/pricing"
        return path.split("{", 1)[0].rstrip("/")

    def _attribute(self, matched: str, kind: str, provider_index: dict,
                   self_repo: str) -> str:
        """Return the provider repo a signal points to, or '' if none/self."""
        for prov, data in provider_index.items():
            if prov == self_repo:
                continue
            if kind == "webclient_call":
                for p in data["paths"]:
                    if self._path_prefix(p) and self._path_prefix(p) in matched:
                        return prov
            elif kind == "dto_usage":
                if matched in data["schemas"]:
                    return prov
        return ""

    # ---- scan one repo ----------------------------------------------
    def scan(self, repo: str, ref: str, provider_index: dict) -> CodeScan:
        scan = CodeScan(repo=repo, ref=ref)
        tmp = tempfile.mkdtemp(prefix=f"scan-{repo}-")
        try:
            sha = self._shallow_clone(repo, ref, tmp)
            if sha is None:
                scan.errors.append(f"clone failed for {repo}@{ref}")
                return scan
            scan.commit_sha = sha

            all_schemas = set()
            for d in provider_index.values():
                all_schemas |= d["schemas"]

            for root, _dirs, files in os.walk(tmp):
                if "/.git" in root:
                    continue
                for fn in files:
                    ext = os.path.splitext(fn)[1].lower()
                    if ext not in CODE_EXTS:
                        continue
                    fpath = os.path.join(root, fn)
                    rel = os.path.relpath(fpath, tmp)
                    try:
                        with open(fpath, "r", encoding="utf-8",
                                  errors="replace") as fh:
                            lines = fh.readlines()
                    except Exception:  # noqa: BLE001
                        continue
                    self._scan_lines(rel, lines, ext, provider_index,
                                     all_schemas, repo, scan)
            return scan
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _scan_lines(self, rel, lines, ext, provider_index, all_schemas,
                    self_repo, scan):
        is_config = ext in {".yaml", ".yml", ".properties"}
        for i, line in enumerate(lines, start=1):
            # config base-URLs
            if is_config:
                m = CONFIG_URL_PATTERN.match(line.strip())
                if m and ("http" in m.group(2) or "service" in m.group(1).lower()):
                    scan.signals.append(Signal(
                        kind="config_url", matched=m.group(1),
                        file=rel, line=i))
                continue

            # WebClient call paths
            um = CALL_PATTERNS[0].search(line)
            if um:
                path = um.group(1)
                prov = self._attribute(path, "webclient_call",
                                       provider_index, self_repo)
                scan.signals.append(Signal(
                    kind="webclient_call", matched=path, file=rel,
                    line=i, provider=prov))

            # DTO / schema usage (only for schemas known to some provider)
            for schema in all_schemas:
                # word-boundary match to avoid partial hits
                if re.search(rf'\b{re.escape(schema)}\b', line):
                    prov = self._attribute(schema, "dto_usage",
                                           provider_index, self_repo)
                    if prov:
                        scan.signals.append(Signal(
                            kind="dto_usage", matched=schema, file=rel,
                            line=i, provider=prov))
