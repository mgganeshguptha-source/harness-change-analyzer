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
    ok("cap defaults to None when unset", si.cap is None)
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


def test_code_signals(tmp_root):
    print("code-signal scanner (local git)")
    import subprocess
    from code_signals import CodeSignalScanner, CodeScan
    from repo_reader import RepoSnapshot, ContractDoc

    # build a fake consumer repo with a WebClient call to /pricing and a DTO use
    repo_dir = os.path.join(tmp_root, "inventory-service")
    src = os.path.join(repo_dir, "src")
    os.makedirs(src)
    with open(os.path.join(src, "Client.java"), "w") as fh:
        fh.write('class C { void go(){ webClient.get()'
                 '.uri("/pricing/{id}", id).retrieve(); Price p; } }\n')
    with open(os.path.join(repo_dir, "application.yml"), "w") as fh:
        fh.write("pricing-service:\n  url: http://pricing-service/api\n")
    subprocess.run(["git", "init", "-q"], cwd=repo_dir)
    subprocess.run(["git", "add", "."], cwd=repo_dir)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "init"], cwd=repo_dir)

    # provider index: pricing owns /pricing and Price schema
    prov_snap = RepoSnapshot(name="pricing-service", ref="main", owner="o")
    prov_snap.contracts.append(ContractDoc(
        path="api/pricing.yaml",
        text="openapi: 3.0.0\npaths:\n  /pricing/{id}: {}\n"
             "components:\n  schemas:\n    Price: {type: object}\n",
        signals=set()))
    idx = CodeSignalScanner.build_provider_index([prov_snap])
    ok("provider index has path", "/pricing/{id}" in idx["pricing-service"]["paths"])
    ok("provider index has schema", "Price" in idx["pricing-service"]["schemas"])

    # scan by pointing the scanner's clone at our local repo via file:// override
    scanner = CodeSignalScanner(owner="o")
    scanner._clone_url = lambda repo: repo_dir      # clone from local path
    scan = scanner.scan("inventory-service", "master", idx)
    kinds = {s.kind for s in scan.signals}
    ok("webclient call detected", "webclient_call" in kinds)
    ok("dto usage detected", "dto_usage" in kinds)
    ok("config url detected", "config_url" in kinds)
    edges = scan.edges_to("pricing-service")
    ok("edge attributed to pricing-service", len(edges) >= 1)
    ok("evidence has commit sha", bool(scan.commit_sha))


def test_change_type():
    print("change-type classification")
    from change_type import classify
    # structural
    c1 = classify({"title": "Add PLATINUM to discountTier enum",
                   "description": "add a new enum value to the API contract"})
    ok("structural -> contract", c1["change_type"] == "contract")
    ok("structural not flagged", c1["contract_only_insufficient"] is False)
    # behavioural
    c2 = classify({"title": "Change discount calculation rounding",
                   "description": "recompute the effective price using a new "
                                  "business rule for rounding"})
    ok("behavioural detected", c2["behavioural"] is True)
    ok("behavioural flagged insufficient",
       c2["contract_only_insufficient"] is True)
    # unknown -> cautious
    c3 = classify({"title": "zzz", "description": "qqq"})
    ok("unknown flagged insufficient", c3["contract_only_insufficient"] is True)


def test_clarification_gate():
    print("clarification gate")
    import repo_reader as rr
    from repo_reader import RepoSnapshot, ContractDoc
    rr.RepoReader.read = lambda self, n, r, paths: (lambda s: (
        s.contracts.append(ContractDoc(path=paths[0],
            text="openapi: 3.0.0\ninfo:\n  version: v1\n",
            signals={"pricing"})) or s))(RepoSnapshot(name=n, ref=r, owner="X"))
    rr.RepoReader.branch_exists = lambda self, repo, ref: True
    from analyzer import analyze

    def low(prompt, model=None, parse=True):
        return {"provider": {"repo": "pricing-service", "contract": "a", "contract_version": "v1"},
                "consumers": [], "potentially_affected": [], "dependencies": [],
                "contract_change": {"type": "unknown"}, "confidence": 0.4,
                "clarifications_needed": ["ambiguous scope"],
                "assumptions": ["assumed X"], "evidence": []}
    import os
    os.environ["HARNESS_CODE_SCAN"] = "off"
    cs = analyze({"story": "X", "title": "t", "description": "d",
                  "branch_default": "main", "branch_overrides": {}},
                 REG, owner="O", reasoner=low)
    ok("low conf -> NEEDS_CLARIFICATION",
       cs["change_set"]["status"] == "NEEDS_CLARIFICATION")
    ok("clarifications recorded",
       cs["change_set"]["analysis"]["clarifications_needed"] == ["ambiguous scope"])
    ok("assumptions recorded",
       cs["change_set"]["analysis"]["assumptions"] == ["assumed X"])

    def high(prompt, model=None, parse=True):
        return {"provider": {"repo": "pricing-service", "contract": "a", "contract_version": "v1"},
                "consumers": [{"repo": "inventory-service"}],
                "potentially_affected": [], "dependencies": [],
                "contract_change": {"type": "backward_compatible"},
                "confidence": 0.95, "clarifications_needed": [],
                "assumptions": [], "evidence": []}
    cs2 = analyze({"story": "X", "title": "t", "description": "d",
                   "branch_default": "main", "branch_overrides": {}},
                  REG, owner="O", reasoner=high)
    ok("high conf, no questions -> PROPOSED",
       cs2["change_set"]["status"] == "PROPOSED")
    # custom threshold via story
    cs3 = analyze({"story": "X", "title": "t", "description": "d",
                   "branch_default": "main", "branch_overrides": {},
                   "clarify_threshold": 0.99},
                  REG, owner="O", reasoner=high)
    ok("custom threshold applied",
       cs3["change_set"]["status"] == "NEEDS_CLARIFICATION")


if __name__ == "__main__":
    import tempfile
    test_registry()
    test_signals_and_shortlist()
    test_change_set_guards()
    test_story_provider()
    test_change_type()
    test_clarification_gate()
    with tempfile.TemporaryDirectory() as d:
        test_plan(d)
    with tempfile.TemporaryDirectory() as d:
        test_code_signals(d)
    print(f"\n{PASSED} passed, {FAILED} failed")
    sys.exit(1 if FAILED else 0)
