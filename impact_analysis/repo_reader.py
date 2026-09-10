"""
Derive-on-read repository reader (READ ONLY) + contract signal parsing.

For each repo, resolves its contract_paths (exact files and/or globs like
api/*.yaml) at target_branch via the GitHub REST API, fetches each contract,
and parses deterministic SIGNALS (paths, operationIds, tags, schema names) used
by the lexical shortlist. NO LLM here — pure fetch + parse.

Reads happen at target_branch so the picture is aligned by construction (no
stored index, no drift). Reads are READ-ONLY: no branch/PR writes.

Stdlib + PyYAML only.
"""

from __future__ import annotations

import base64
import fnmatch
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

import yaml

GITHUB_API = os.environ.get("GITHUB_API_URL", "https://api.github.com")


@dataclass
class ContractDoc:
    path: str
    text: str
    signals: set = field(default_factory=set)   # lowercased tokens for matching


@dataclass
class RepoSnapshot:
    name: str
    ref: str
    owner: str
    contracts: list = field(default_factory=list)   # list[ContractDoc]
    errors: list = field(default_factory=list)

    @property
    def contract_found(self) -> bool:
        return bool(self.contracts)

    @property
    def all_signals(self) -> set:
        s = set()
        for c in self.contracts:
            s |= c.signals
        return s

    def combined_text(self, limit: int = 4000) -> str:
        """Concatenated contract text for the reasoning prompt (bounded)."""
        if not self.contracts:
            return "(no contract file found at ref)"
        out = []
        budget = limit
        for c in self.contracts:
            chunk = c.text[:budget]
            out.append(f"# {c.path}\n{chunk}")
            budget -= len(chunk)
            if budget <= 0:
                out.append("...[truncated]")
                break
        return "\n\n".join(out)


def parse_signals(text: str) -> set:
    """Extract lowercased tokens from an OpenAPI doc: paths, operationIds, tags,
    schema names. Falls back to raw token scan if it isn't valid YAML."""
    signals: set = set()
    try:
        doc = yaml.safe_load(text)
    except Exception:  # noqa: BLE001
        doc = None

    def add(s):
        if not s:
            return
        for tok in _tokenize(str(s)):
            signals.add(tok)

    if isinstance(doc, dict):
        for p in (doc.get("paths") or {}):
            add(p)                                  # /members/{id}/eligibility
        for p, ops in (doc.get("paths") or {}).items():
            if isinstance(ops, dict):
                for method, op in ops.items():
                    if isinstance(op, dict):
                        add(op.get("operationId"))
                        for t in (op.get("tags") or []):
                            add(t)
        comps = (doc.get("components") or {}).get("schemas") or {}
        for schema_name in comps:
            add(schema_name)
        for t in (doc.get("tags") or []):
            if isinstance(t, dict):
                add(t.get("name"))
            else:
                add(t)
    else:
        # not parseable as OpenAPI — scan tokens so we still get some signal
        add(text[:5000])
    return signals


def _tokenize(s: str) -> list:
    import re
    # split camelCase, snake, kebab, slashes, punctuation -> lowercase words
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)
    return [w for w in re.findall(r"[A-Za-z][A-Za-z0-9]{1,}", spaced.lower())
            if len(w) > 1]


class RepoReader:
    def __init__(self, owner: str, token: str | None = None):
        self.owner = owner
        self.token = token or os.environ.get("GITHUB_TOKEN")

    def _request(self, url: str):
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/vnd.github+json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def branch_exists(self, repo: str, ref: str) -> bool:
        """True if `ref` (branch) exists in the repo."""
        url = (f"{GITHUB_API}/repos/{self.owner}/{repo}/branches/"
               f"{urllib.parse.quote(ref)}")
        try:
            data = self._request(url)
        except urllib.error.HTTPError:
            return False
        return bool(data and data.get("name"))

    def _list_dir(self, repo: str, dirpath: str, ref: str) -> list:
        url = (f"{GITHUB_API}/repos/{self.owner}/{repo}/contents/"
               f"{urllib.parse.quote(dirpath)}?ref={urllib.parse.quote(ref)}")
        data = self._request(url)
        return data if isinstance(data, list) else []

    def _get_file(self, repo: str, path: str, ref: str) -> str | None:
        url = (f"{GITHUB_API}/repos/{self.owner}/{repo}/contents/"
               f"{urllib.parse.quote(path)}?ref={urllib.parse.quote(ref)}")
        data = self._request(url)
        if not data or "content" not in data:
            return None
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    def _resolve_glob(self, repo: str, pattern: str, ref: str) -> list:
        """Resolve one exact path or a single-directory glob (api/*.yaml)."""
        if "*" not in pattern and "?" not in pattern:
            return [pattern]
        dirpath = os.path.dirname(pattern) or "."
        base = os.path.basename(pattern)
        listing = self._list_dir(repo, dirpath if dirpath != "." else "", ref)
        out = []
        for item in listing:
            if item.get("type") == "file" and fnmatch.fnmatch(item["name"], base):
                out.append(item["path"])
        return out

    def read(self, name: str, ref: str, contract_paths: list) -> RepoSnapshot:
        snap = RepoSnapshot(name=name, ref=ref, owner=self.owner)
        resolved: list = []
        for pattern in contract_paths:
            try:
                resolved.extend(self._resolve_glob(name, pattern, ref))
            except Exception as e:  # noqa: BLE001
                snap.errors.append(f"resolve '{pattern}' failed: {e}")
        # de-dup, keep order
        seen, paths = set(), []
        for p in resolved:
            if p not in seen:
                seen.add(p)
                paths.append(p)

        for path in paths:
            try:
                text = self._get_file(name, path, ref)
                if text is not None:
                    snap.contracts.append(
                        ContractDoc(path=path, text=text,
                                    signals=parse_signals(text)))
            except Exception as e:  # noqa: BLE001
                snap.errors.append(f"read '{path}' failed: {e}")
        return snap
