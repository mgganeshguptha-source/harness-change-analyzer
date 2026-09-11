"""
Change Set validation.

Phase 1 (analyze -> plan) uses validate() to check an approved change set against
the registry before the plan is generated. Manifest generation (to_manifest) and
the cross-repo orchestrator were Phase 2 and have been moved aside; if you revive
auto-orchestration, restore to_manifest from the phase2-orchestration set.

Branch model: analysis reads each repo at a branch chosen by the developer
harness cuts feature/<story>-<slug> from it and PRs back into it. Those fields
live on the change set and flow into the plan.
"""

from __future__ import annotations

from registry import ServiceRegistry

CONFIDENCE_THRESHOLD = 70   # below this, a human must explicitly APPROVE


class ValidationError(Exception):
    pass


def validate(change_set: dict, registry: ServiceRegistry) -> list[str]:
    """Return a list of problems. Empty list == valid."""
    cs = change_set.get("change_set", {})
    problems: list[str] = []

    if not cs.get("story"):
        problems.append("story is required")
    if not cs.get("branch_default"):
        problems.append("branch_default is required "
                        "(from analysis_target_branch.yaml)")

    provider = cs.get("provider", {}) or {}
    prov_repo = provider.get("repo")
    if not prov_repo:
        problems.append("provider.repo is required")
    elif not registry.contains(prov_repo):
        problems.append(f"provider.repo '{prov_repo}' not in registry")

    consumer_repos = []
    for c in cs.get("consumers", []) or []:
        repo = c.get("repo")
        consumer_repos.append(repo)
        if repo and not registry.contains(repo):
            problems.append(f"consumer '{repo}' not in registry")

    affected_repos = []
    for a in cs.get("potentially_affected", []) or []:
        repo = a.get("repo")
        affected_repos.append(repo)
        if repo and not registry.contains(repo):
            problems.append(f"potentially_affected '{repo}' not in registry")

    # dependency edges may reference provider, consumers, OR potentially_affected
    # (a downstream repo can be flagged as impacted without being a direct
    # contract consumer — the edge to it is still valid).
    known = set(filter(None, [prov_repo] + consumer_repos + affected_repos))
    for edge in cs.get("dependencies", []) or []:
        for side in ("from", "to"):
            r = edge.get(side)
            if r and r not in known:
                problems.append(
                    f"dependency edge references unknown repo '{r}'")

    return problems


def is_release_ready(change_set: dict) -> tuple[bool, str]:
    """A change set may become a plan only if APPROVED, or high-confidence."""
    cs = change_set.get("change_set", {})
    status = cs.get("status", "PROPOSED")
    conf = cs.get("analysis", {}).get("confidence", 0)

    if status == "APPROVED":
        return True, "approved by human"
    if status == "REJECTED":
        return False, "change set was rejected"
    if conf >= CONFIDENCE_THRESHOLD:
        return False, (f"confidence {conf} >= threshold but status is "
                       f"'{status}'; human approval still required")
    return False, (f"confidence {conf} < threshold {CONFIDENCE_THRESHOLD}; "
                   f"needs human clarification/approval")
