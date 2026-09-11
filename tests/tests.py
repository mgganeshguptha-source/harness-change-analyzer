"""
tests.py — Phase-1 (analyze -> plan) plumbing tests. No SDK, no network, no credits.

Covers:
  * registry (contract_paths, no stream)
  * contract signal parsing + lexical shortlist (term overlap, widen-on-weak)
  * change-set validation
  * story provider (repo folder, frontmatter, attachments)
  * plan generation (per-repo stories + dependency-ordered PLAN.md)

Run:  python tests/tests.py
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "impact_analysis"))

from registry import ServiceRegistry            # noqa: E402
from change_set import validate, is_release_ready  # noqa: E402
from repo_reader import parse_signals, RepoSnapshot, ContractDoc  # noqa: E402
from shortlist import shortlist                  # noqa: E402

PASSED = 0
FAILED = 0


def ok(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}  {detail}")


REG = os.path.join(ROOT, "config", "service-registry.yaml")


def _snap(name, signals):
    s = RepoSnapshot(name=name, ref="PM_Sep", owner="o")
    s.contracts.append(ContractDoc(path="api/x.yaml", text="", signals=set(signals)))
    return s


def test_registry():
    print("registry")
    reg = ServiceRegistry.load(REG)
    ok("contract_paths list", reg.get("pricing-service").contract_paths ==
       ["api/pricing.yaml"])
    ok("all repos", set(reg.names()) ==
       {"inventory-service", "pricing-service", "book-service"})
    ok("contains", reg.contains("book-service") and not reg.contains("ghost"))
    ok("no stream attr", not hasattr(reg.get("book-service"), "stream"))


def test_signals_and_shortlist():
    print("signal parsing + shortlist")
    oas = """openapi: 3.0.0
info: {title: member, version: v2}
paths:
  /members/{id}/eligibility:
    get:
      operationId: getMemberEligibility
      tags: [member]
components:
  schemas:
    MemberEligibility: {type: object}
"""
    sig = parse_signals(oas)
    ok("parses path token", "members" in sig)
    ok("parses schema token", "eligibility" in sig)
    ok("splits camelCase opId", "member" in sig and "eligibility" in sig)

    snaps = [
        _snap("member-service", {"members", "member", "eligibility", "preferences"}),
        _snap("provider-service", {"provider", "directory", "search"}),
        _snap("billing-service", {"billing", "invoice"}),
    ]
    # strong lexical match
    res = shortlist(["member", "eligibility"], snaps, cap=10, min_candidates=1)
    ok("top candidate is member-service",
       res["candidates"][0].name == "member-service")
    ok("not widened on strong match", res["widened"] is False)

    # weak match -> widen to all
    res2 = shortlist(["nonexistentterm"], snaps, cap=10, min_candidates=3)
    ok("widened on weak match", res2["widened"] is True)
    ok("widen returns all repos", len(res2["candidates"]) == 3)


def test_change_set_guards():
    print("change set guards")
    reg = ServiceRegistry.load(REG)
    good = {"change_set": {
        "story": "BCBSM-1", "title": "Add field", "status": "APPROVED",
        "branch_default": "main", "analysis": {"confidence": 90},
        "provider": {"repo": "pricing-service", "contract": "api/pricing.yaml",
                     "contract_version": "v2"},
        "consumers": [{"repo": "inventory-service"}],
        "dependencies": [{"from": "pricing-service", "to": "inventory-service"}],
        "contract_change": {"type": "backward_compatible"}, "options": {}}}
    ok("valid change set", validate(good, reg) == [])
    # dependency edge to a potentially_affected repo is allowed
    aff = {"change_set": dict(good["change_set"],
        consumers=[{"repo": "inventory-service"}],
        potentially_affected=[{"repo": "book-service", "reason": "downstream"}],
        dependencies=[{"from": "pricing-service", "to": "inventory-service"},
                      {"from": "inventory-service", "to": "book-service"}])}
    ok("edge to potentially_affected allowed", validate(aff, reg) == [])
    bad = {"change_set": dict(good["change_set"], consumers=[{"repo": "ghost"}])}
    ok("unknown repo rejected", validate(bad, reg) != [])
    nobranch = {"change_set": dict(good["change_set"], branch_default="")}
    ok("missing branch_default rejected", validate(nobranch, reg) != [])
    low = {"change_set": dict(good["change_set"], status="PROPOSED",
                             analysis={"confidence": 30})}
    ready, _ = is_release_ready(low)
    ok("low-confidence proposed not release-ready", not ready)


def test_story_provider():
    print("story provider (repo folder)")
    from story_provider import RepoFolderProvider
    prov = RepoFolderProvider(stories_root=os.path.join(ROOT, "stories"))
    si = prov.get("BCBSM-1234")
    ok("story id", si.story == "BCBSM-1234")
    ok("branch default from analysis file", si.branch_default == "main")
    ok("description body present", "loyaltyTier" in si.description)
    ok("text attachment inlined", "example-response.json" in si.attachments_text)
    try:
        prov.get("NO-SUCH")
        ok("missing story raises", False)
    except FileNotFoundError:
        ok("missing story raises", True)


def test_plan(tmp_root):
    print("plan generation")
    from plan import generate_plan
    from reasoning import mock_reason
    cs = {"change_set": {
        "story": "BCBSM-7", "title": "Add field", "status": "APPROVED",
        "branch_default": "main", "description": "expose and consume a field",
        "provider": {"repo": "pricing-service", "contract": "api/pricing.yaml",
                     "contract_version": "v2"},
        "consumers": [{"repo": "inventory-service"}],
        "potentially_affected": [{"repo": "book-service",
                                  "reason": "downstream of inventory"}],
        "dependencies": [{"from": "pricing-service", "to": "inventory-service"},
                         {"from": "inventory-service", "to": "book-service"}],
        "contract_change": {"type": "backward_compatible"}, "options": {}}}
    res = generate_plan(cs, stories_root=tmp_root, reasoner=mock_reason)
    ok("plan file created", os.path.exists(res["plan_path"]))
    ok("provider wave first", res["waves"][0] == ["pricing-service"])
    ok("book-service (affected) in a later wave",
       any("book-service" in w for w in res["waves"]))
    ok("story drafted for affected repo",
       "book-service" in res["story_paths"])
    plan_txt = open(res["plan_path"]).read()
    ok("no hardcoded base=PM_Sep", "base=PM_Sep" not in plan_txt
       and "base = PM_Sep" not in plan_txt)
    ok("developer sets base", "your target release branch" in plan_txt
       or "your base branch" in plan_txt)
    cs2 = {"change_set": dict(cs["change_set"], status="PROPOSED")}
    try:
        generate_plan(cs2, stories_root=tmp_root, reasoner=mock_reason)
        ok("unapproved refused", False)
    except ValueError:
        ok("unapproved refused", True)


if __name__ == "__main__":
    import tempfile
    test_registry()
    test_signals_and_shortlist()
    test_change_set_guards()
    test_story_provider()
    with tempfile.TemporaryDirectory() as d:
        test_plan(d)
    print(f"\n{PASSED} passed, {FAILED} failed")
    sys.exit(1 if FAILED else 0)
