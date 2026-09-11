"""
Impact Analyzer — story -> candidate Change Set, with pre-LLM narrowing.

Pipeline (rebuild-each-run, no stored index, no stream):
  1. Story arrives (id, title, description, target_branch). No stream tag.
  2. Extract deterministic search terms from the story.
  3. Derive-on-read: read EVERY registry repo's contract(s) at target_branch,
     in parallel. No LLM — fetch + parse signals only.
  4. Lexical shortlist: term-overlap score -> top ~10 candidates
     (widen to all repos if lexical signal is weak — recall safety).
  5. Copilot reasons over the SHORTLIST only (not all repos).
  6. Emit a PROPOSED Change Set for human approval.

The registry is the repo universe; branch is per-story (target_branch); repos
may have multiple contracts (contract_paths). Capabilities are derived from
contract signals, never tagged.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from registry import ServiceRegistry
from repo_reader import RepoReader
from reasoning import get_reasoner
from naming import feature_branch
from shortlist import shortlist

_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "for", "on", "with",
    "add", "support", "retrieve", "retrieving", "display", "through", "via",
    "s", "it", "their", "this", "that", "as", "be", "is", "are", "new",
    "allow", "enable", "update", "get", "set", "so", "can", "will", "should",
}

MAX_READ_WORKERS = 8


def extract_terms(story_text: str, max_terms: int = 12) -> list:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", story_text)
    words = re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", spaced.lower())
    seen, terms = set(), []
    for w in words:
        if w in _STOPWORDS or w in seen:
            continue
        seen.add(w)
        terms.append(w)
        if len(terms) >= max_terms:
            break
    return terms


def build_prompt(story: dict, candidates: list) -> str:
    blocks = []
    for s in candidates:
        blocks.append(
            f"### repo: {s.name}  (ref: {s.ref})\n"
            f"contracts_found: {s.contract_found}\n"
            f"contract_content:\n{s.combined_text()}\n"
        )
    repos_section = "\n".join(blocks)
    return f"""You are the Impact Analyzer for a cross-repo AI-SDLC harness.
Given a business story and read-only snapshots of CANDIDATE repositories
(pre-filtered by lexical match, each read at the story's target branch),
determine the cross-repo impact.

RULES:
- The PROVIDER is the repo that OWNS the interface/contract being changed.
- CONSUMERS are repos that must adapt to that contract change.
- Use the contract content as evidence. If a repo references the area but shows
  no use of the impacted interface, list it under potentially_affected (NOT
  consumers).
- These candidates were pre-filtered; if NONE truly fit, say so via low
  confidence and an empty provider — do not force a choice.
- If evidence is weak or ambiguous, LOWER the confidence score.
- Output STRICT JSON only. No prose, no markdown, no code fences.

STORY:
id: {story.get('story')}
title: {story.get('title')}
description: {story.get('description')}

CANDIDATE REPOSITORIES:
{repos_section}

Return JSON with EXACTLY this shape:
{{
  "provider": {{"repo": "", "contract": "", "contract_version": ""}},
  "consumers": [{{"repo": "", "evidence": ""}}],
  "potentially_affected": [{{"repo": "", "reason": ""}}],
  "dependencies": [{{"from": "", "to": ""}}],
  "contract_change": {{"type": "backward_compatible|breaking|unknown"}},
  "confidence": 0,
  "evidence": ["short bullet strings"]
}}"""


def analyze(story: dict, registry_path: str, owner: str,
            reasoner=None) -> dict:
    branch_default = story.get("branch_default")
    if not branch_default:
        raise ValueError("story.branch_default is required "
                         "(from analysis_target_branch.yaml)")
    branch_overrides = story.get("branch_overrides", {}) or {}

    reg = ServiceRegistry.load(registry_path)
    reader = RepoReader(owner=owner)
    reasoner = reasoner or get_reasoner()
    terms = extract_terms(
        f"{story.get('title', '')} {story.get('description', '')}")

    entries = reg.all()
    # per-repo resolved branch: override if given, else default
    repo_branch = {e.name: branch_overrides.get(e.name, branch_default)
                   for e in entries}

    # validate a per-repo override doesn't name an unknown repo
    unknown = [r for r in branch_overrides if not reg.contains(r)]
    if unknown:
        raise ValueError(
            "analysis_target_branch.yaml overrides name repos not in the "
            f"registry: {', '.join(sorted(unknown))}")

    # batch branch-existence check — collect ALL missing, then hard-fail
    def _check(entry):
        ref = repo_branch[entry.name]
        return (entry.name, ref, reader.branch_exists(entry.name, ref))

    missing = []
    with ThreadPoolExecutor(max_workers=MAX_READ_WORKERS) as ex:
        for name, ref, exists in ex.map(_check, entries):
            if not exists:
                missing.append((name, ref))
    if missing:
        lines = "\n".join(f"  - {repo}: branch '{ref}' not found"
                          for repo, ref in sorted(missing))
        raise ValueError(
            "Analysis aborted — required branches are missing:\n" + lines +
            "\n\nFix analysis_target_branch.yaml (default/overrides) or create "
            "the branches, then re-run.")

    # derive-on-read ALL repos at their resolved branch, in parallel (no LLM)
    def _read(entry):
        return reader.read(entry.name, repo_branch[entry.name],
                           entry.contract_paths)

    snapshots = []
    with ThreadPoolExecutor(max_workers=MAX_READ_WORKERS) as ex:
        for snap in ex.map(_read, entries):
            snapshots.append(snap)

    # lexical shortlist -> candidates (widen if weak)
    sl = shortlist(terms, snapshots)
    candidates = sl["candidates"]
    analyzed_refs = {s.name: repo_branch[s.name] for s in candidates}
    shortlist_audit = [{"repo": s.name, "score": s.score,
                        "matched": s.matched} for s in sl["scored"]]

    # reason over candidates only
    prompt = build_prompt(story, candidates)
    model = story.get("model")
    result = reasoner(prompt, model) if model else reasoner(prompt)
    if isinstance(result, str):
        from reasoning import parse_json
        result = parse_json(result)

    return {
        "change_set": {
            "story": story.get("story"),
            "title": story.get("title", ""),
            "branch_default": branch_default,
            "branch_overrides": branch_overrides,
            "description": story.get("description", ""),
            "feature_branch": feature_branch(story.get("story"),
                                             story.get("title", "")),
            "status": "PROPOSED",
            "analysis": {
                "engine": "copilot-sdk",
                "model": story.get("model") or "default",
                "confidence": result.get("confidence", 0),
                "analyzed_refs": analyzed_refs,
                "all_repo_refs": repo_branch,
                "shortlist_widened": sl["widened"],
                "shortlist_scores": shortlist_audit,
                "evidence": result.get("evidence", []),
            },
            "provider": result.get("provider", {}),
            "consumers": result.get("consumers", []),
            "potentially_affected": result.get("potentially_affected", []),
            "dependencies": result.get("dependencies", []),
            "contract_change": result.get("contract_change",
                                          {"type": "unknown"}),
            "options": {
                "merge": "manual",
                "contract_gate": "required",
                "parallel": True,
            },
        }
    }
