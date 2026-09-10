"""
plan.py — turn an APPROVED change set into a developer-executable plan.

Two outputs (Phase-1 model: analyze -> plan -> human runs SDLC-Harness per repo):

  1. Per-repo user story files:
        stories/<story>/per-repo/<repo>.md
     AI-drafted from the main story + the repo's role (provider/consumer) and
     the contract, so each repo's harness run has a focused story to consume.

  2. A human-readable execution plan:
        stories/<story>/per-repo/PLAN.md
     Repo details, dependency order (from the change set edges), and exact
     SDLC-Harness run instructions per repo (feature_id, base, story file path,
     and — only where a dependency edge exists — "run after <dep>'s PR is merged
     into <base>").

No orchestration, no repository_dispatch. The developer/lead reads PLAN.md and
triggers each repo's SDLC-Harness manually.

Per-repo story drafting uses the same reasoning backend as analysis
(mock | copilot), so it runs end-to-end today with mock.
"""

from __future__ import annotations

import os

from reasoning import get_reasoner, parse_json


def _toposort(provider: str, consumers: list[str],
              edges: list[dict]) -> list[list[str]]:
    """Waves from dependency edges. Provider (no deps) first; repos whose deps
    are all satisfied come next; independent repos share a wave."""
    repos = [provider] + [c for c in consumers if c != provider]
    deps: dict[str, set] = {r: set() for r in repos}
    for e in edges or []:
        frm, to = e.get("from"), e.get("to")
        # edge from->to means 'to' consumes 'from' => 'to' depends on 'from'
        if to in deps and frm in repos:
            deps[to].add(frm)

    waves, done, remaining = [], set(), set(repos)
    while remaining:
        ready = sorted(r for r in remaining if deps[r] <= done)
        if not ready:                      # safety: break cycles deterministically
            ready = [sorted(remaining)[0]]
        waves.append(ready)
        done |= set(ready)
        remaining -= set(ready)
    return waves


def _deps_of(repo: str, edges: list[dict]) -> list[str]:
    return sorted({e["from"] for e in (edges or [])
                   if e.get("to") == repo and e.get("from")})


# ---------------------------------------------------------------------
# per-repo story drafting (AI)
# ---------------------------------------------------------------------
def _per_repo_prompt(cs: dict, repo: str, role: str, contract: str) -> str:
    return f"""You are drafting a focused, single-repository user story for one
service that is part of a larger cross-repo change. Output MARKDOWN only (no code
fences), suitable to be the story input for that repo's automated harness run.

PARENT STORY:
id: {cs.get('story')}
title: {cs.get('title')}
description:
{cs.get('description', '(see change set)')}

THIS REPO:
name: {repo}
role: {role}            # provider owns the contract; consumer adapts to it
contract: {contract}

Write the story for THIS repo only. Include:
- a one-line title,
- what THIS repo must change (scoped to its role),
- acceptance criteria specific to this repo,
- for a consumer: note it must consume the {contract} contract as changed by the
  provider; for a provider: note it owns and changes {contract}.
Keep it concise and implementation-focused. MARKDOWN only."""


def _draft_repo_story(cs: dict, repo: str, role: str, contract: str,
                      reasoner) -> str:
    prompt = _per_repo_prompt(cs, repo, role, contract)
    out = reasoner(prompt)
    # reasoner may return dict (mock/JSON backends) or str (markdown). Normalise.
    if isinstance(out, dict):
        # mock backend returns the impact-analysis JSON shape; fall back to a
        # deterministic template so plan generation still runs end-to-end.
        return _fallback_repo_story(cs, repo, role, contract)
    return out.strip()


def _fallback_repo_story(cs: dict, repo: str, role: str, contract: str) -> str:
    owns = "owns and changes" if role == "provider" else "consumes"
    return f"""# {cs.get('story')} — {repo}

**Parent story:** {cs.get('title')}
**Role:** {role}
**Contract:** {repo} {owns} `{contract}`

## What this repo must change
- Implement the {role}-side changes for "{cs.get('title')}".
- {"Update the contract and its implementation." if role == "provider" else f"Adapt to the changed `{contract}` contract from the provider."}

## Acceptance criteria
- Changes are scoped to {repo}.
- {"Contract " + contract + " reflects the new version and stays backward compatible unless a breaking change is declared." if role == "provider" else "This service builds and its tests pass against the updated contract."}

_(Draft generated without AI reasoning — mock backend. Run with
HARNESS_REASONING=copilot for an AI-authored per-repo story.)_
"""


# ---------------------------------------------------------------------
# plan rendering
# ---------------------------------------------------------------------
def _render_plan(cs: dict, waves: list[list[str]], edges: list[dict],
                 role_of: dict, story_paths: dict) -> str:
    story = cs.get("story")
    feature_id = story  # cross-repo story id == feature_id per repo (confirmed)
    analyzed = (cs.get("analysis", {}) or {}).get("all_repo_refs", {}) or {}

    lines = [
        f"# Execution Plan — {story}",
        "",
        f"**Story:** {cs.get('title')}  ",
        f"**feature_id for every repo:** `{feature_id}`",
        "",
        "> This plan is produced by harness-change-analyzer (analysis only). A",
        "> developer/lead runs SDLC-Harness **manually** for each repo. Sequencing",
        "> is human-enforced. **You choose the `base`** (the release/dev branch to",
        "> PR into, e.g. PM_Sep) when you run SDLC-Harness — the analyzer does not",
        "> decide it. The branch shown per repo below is only what analysis READ.",
        "",
        "## Repos in this change",
        "",
    ]
    for repo, role in role_of.items():
        deps = _deps_of(repo, edges)
        dep_txt = f"depends on {', '.join(deps)}" if deps else "no dependencies"
        aref = analyzed.get(repo)
        aref_txt = f", analyzed at `{aref}`" if aref else ""
        lines.append(f"- **{repo}** — {role} ({dep_txt}{aref_txt})")
    lines += ["", "## Run order", ""]

    step = 1
    for wave in waves:
        if len(wave) == 1:
            repo = wave[0]
            deps = _deps_of(repo, edges)
            lines.append(f"### Step {step}: {repo}  ({role_of.get(repo,'?')})")
            lines += _run_block(repo, feature_id, story_paths.get(repo), deps)
            lines.append("")
            step += 1
        else:
            names = ", ".join(wave)
            lines.append(f"### Step {step}: {names}  "
                         f"(no dependencies between them — run in parallel / any order)")
            for repo in wave:
                deps = _deps_of(repo, edges)
                lines.append(f"\n**{repo}** ({role_of.get(repo,'?')})")
                lines += _run_block(repo, feature_id, story_paths.get(repo), deps)
            lines.append("")
            step += 1

    lines += [
        "## How to run each repo",
        "",
        "1. Copy the repo's per-repo story file into that repo's expected story",
        "   location (per your SDLC-Harness setup).",
        "2. In that repo: Actions → **SDLC-Harness** → Run workflow.",
        f"3. Set `feature_id = {feature_id}` and set `base` to your target",
        "   release/dev branch (e.g. PM_Sep).",
        "4. Review the PR the harness raises; merge into your chosen base.",
        "",
        "Where a repo depends on another, run it only **after** the dependency's",
        "PR is merged into your base branch — the harness checks out that base, so",
        "an unmerged upstream change is not visible to it.",
    ]
    return "\n".join(lines) + "\n"


def _run_block(repo: str, feature_id: str,
               story_path: str | None, deps: list[str]) -> list[str]:
    b = [
        "",
        f"- story file: `{story_path}`" if story_path else "- story file: (none)",
        f"- run: SDLC-Harness with `feature_id={feature_id}`, `base=<your target release branch>`",
    ]
    if deps:
        b.append(f"- \u26a0 run only after **{', '.join(deps)}**'s PR is merged "
                 f"into your base branch")
    else:
        b.append("- no upstream dependency — can run immediately")
    return b


# ---------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------
def generate_plan(change_set: dict, stories_root: str = "stories",
                  reasoner=None) -> dict:
    cs = change_set["change_set"]
    if cs.get("status") != "APPROVED":
        raise ValueError(f"change set status is '{cs.get('status')}'; "
                         f"approve it before generating the plan")

    story = cs["story"]
    reasoner = reasoner or get_reasoner()
    provider = cs["provider"]["repo"]
    contract = cs["provider"].get("contract", "")
    consumers = [c["repo"] for c in cs.get("consumers", []) or []]
    edges = cs.get("dependencies", [])

    role_of = {provider: "provider"}
    for c in consumers:
        role_of.setdefault(c, "consumer")

    # 1. per-repo story files
    out_dir = os.path.join(stories_root, story, "per-repo")
    os.makedirs(out_dir, exist_ok=True)
    story_paths = {}
    for repo, role in role_of.items():
        text = _draft_repo_story(cs, repo, role, contract, reasoner)
        path = os.path.join(out_dir, f"{repo}.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        story_paths[repo] = path

    # 2. plan
    waves = _toposort(provider, consumers, edges)
    plan_md = _render_plan(cs, waves, edges, role_of, story_paths)
    plan_path = os.path.join(out_dir, "PLAN.md")
    with open(plan_path, "w", encoding="utf-8") as fh:
        fh.write(plan_md)

    return {"plan_path": plan_path, "story_paths": story_paths,
            "waves": waves}
