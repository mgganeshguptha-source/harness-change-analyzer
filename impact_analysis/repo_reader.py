"""
Derive-on-read repository reader (READ ONLY).

For each candidate repo, fetches the contract file and a shallow set of code
signals AT THE REPO'S RESOLVED REF via the GitHub REST API. No local clone,
no write scope. Because everything is read at the configured ref, the derived
dependency picture is aligned by construction — there is no stored graph to
drift against.

Auth: a token with READ access to the candidate repos (GITHUB_TOKEN env).
The analysis stage must NOT hold write scope; branch/PR creation happens later
in the orchestration layer, only after human approval.

Stdlib only (urllib) to keep the control plane portable.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

GITHUB_API = os.environ.get("GITHUB_API_URL", "https://api.github.com")


@dataclass
class RepoSnapshot:
    name: str
    ref: str
    owner: str
    contract_path: str
    contract_text: str | None = None        # None if not found at ref
    contract_found: bool = False
    code_hits: dict = field(default_factory=dict)   # term -> [paths]
    errors: list[str] = field(default_factory=list)


class RepoReader:
    def __init__(self, owner: str, token: str | None = None):
        self.owner = owner
        self.token = token or os.environ.get("GITHUB_TOKEN")

    def _request(self, url: str) -> dict | list | None:
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

    # ---- contract file at ref ---------------------------------------
    def _get_file(self, repo: str, path: str, ref: str) -> str | None:
        url = f"{GITHUB_API}/repos/{self.owner}/{repo}/contents/{path}?ref={ref}"
        data = self._request(url)
        if not data or "content" not in data:
            return None
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    # ---- code search (repo-scoped) ----------------------------------
    def _search_code(self, repo: str, term: str) -> list[str]:
        # GitHub code search indexes the default branch; treat hits as SIGNALS,
        # not proof. The contract file (read at the exact ref) is the ground truth.
        q = urllib.parse.quote(f'{term} repo:{self.owner}/{repo}')
        url = f"{GITHUB_API}/search/code?q={q}&per_page=5"
        try:
            data = self._request(url)
        except urllib.error.HTTPError:
            return []
        if not data or "items" not in data:
            return []
        return [item["path"] for item in data["items"]]

    # ---- public -----------------------------------------------------
    def read(self, name: str, ref: str, contract_path: str,
             search_terms: list[str]) -> RepoSnapshot:
        snap = RepoSnapshot(name=name, ref=ref, owner=self.owner,
                            contract_path=contract_path)
        try:
            text = self._get_file(name, contract_path, ref)
            snap.contract_text = text
            snap.contract_found = text is not None
        except Exception as e:  # noqa: BLE001
            snap.errors.append(f"contract read failed: {e}")

        for term in search_terms:
            try:
                hits = self._search_code(name, term)
                if hits:
                    snap.code_hits[term] = hits
            except Exception as e:  # noqa: BLE001
                snap.errors.append(f"code search '{term}' failed: {e}")
        return snap
