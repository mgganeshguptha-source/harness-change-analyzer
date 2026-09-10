"""
tests.py — Phase-1 (analyze -> plan) plumbing tests. No SDK, no network, no credits.

Covers:
  * registry stream filtering
  * change-set validation (stream membership, unknown repo, release-ready)
  * story provider (repo folder + frontmatter + attachments)
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


def test_registry():
    print("registry")
    reg = ServiceRegistry.load(REG)
    ok("stream field", reg.get("member-service").stream == "PM")
    ok("contract path", reg.get("member-service").contract_path == "api/member.yaml")
    ok("stream filter PM", set(reg.names("PM")) ==
       {"member-service", "provider-service", "provider-search"})
    ok("stream filter VoC", set(reg.names("VoC")) ==
       {"survey-service", "feedback-service"})
    ok("contains", reg.contains("provider-search") and not reg.contains("ghost"))


def test_change_set_guards():
    print("change set guards")
    reg = ServiceRegistry.load(REG)
    good = {"change_set": {
        "story": "BCBSM-1", "title": "Add loyaltyTier", "status": "APPROVED",
        "stream": "PM", "target_branch": "PM_Sep",
        "analysis": {"confidence": 90},
        "provider": {"repo": "member-service", "contract": "api/member.yaml",
                     "contract_version": "v2"},
        "consumers": [{"repo": "provider-service"}],
        "dependencies": [{"from": "member-service", "to": "provider-service"}],
        "contract_change": {"type": "backward_compatible"}, "options": {}}}
    ok("valid change set", validate(good, reg) == [])

    xstream = {"change_set": dict(good["change_set"],
                                  consumers=[{"repo": "survey-service"}])}
    ok("cross-stream consumer rejected", validate(xstream, reg) != [])

    bad = {"change_set": dict(good["change_set"],
                              consumers=[{"repo": "ghost"}])}
    ok("unknown repo rejected", validate(bad, reg) != [])

    low = {"change_set": dict(good["change_set"],
                              status="PROPOSED",
                              analysis={"confidence": 30})}
    ready, _ = is_release_ready(low)
    ok("low-confidence proposed not release-ready", not ready)


def test_story_provider():
    print("story provider (repo folder)")
    from story_provider import RepoFolderProvider
    root = os.path.join(ROOT, "stories")
    prov = RepoFolderProvider(stories_root=root)
    si = prov.get("BCBSM-1234")
    ok("story id", si.story == "BCBSM-1234")
    ok("stream from frontmatter", si.stream == "PM")
    ok("target_branch from frontmatter", si.target_branch == "PM_Sep")
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
        "stream": "PM", "target_branch": "PM_Sep",
        "description": "expose a field and consume it",
        "provider": {"repo": "member-service", "contract": "api/member.yaml",
                     "contract_version": "v2"},
        "consumers": [{"repo": "provider-service"}, {"repo": "provider-search"}],
        "dependencies": [{"from": "member-service", "to": "provider-service"},
                         {"from": "member-service", "to": "provider-search"}],
        "contract_change": {"type": "backward_compatible"}, "options": {}}}
    res = generate_plan(cs, stories_root=tmp_root, reasoner=mock_reason)
    ok("plan file created", os.path.exists(res["plan_path"]))
    ok("provider wave first", res["waves"][0] == ["member-service"])
    ok("consumers second wave", set(res["waves"][1]) ==
       {"provider-service", "provider-search"})
    ok("per-repo story files created",
       all(os.path.exists(p) for p in res["story_paths"].values()))
    plan_txt = open(res["plan_path"]).read()
    ok("merge instruction present for consumer",
       "merged into `PM_Sep`" in plan_txt)
    cs2 = {"change_set": dict(cs["change_set"], status="PROPOSED")}
    try:
        generate_plan(cs2, stories_root=tmp_root, reasoner=mock_reason)
        ok("unapproved refused", False)
    except ValueError:
        ok("unapproved refused", True)


if __name__ == "__main__":
    import tempfile
    test_registry()
    test_change_set_guards()
    test_story_provider()
    with tempfile.TemporaryDirectory() as d:
        test_plan(d)
    print(f"\n{PASSED} passed, {FAILED} failed")
    sys.exit(1 if FAILED else 0)
