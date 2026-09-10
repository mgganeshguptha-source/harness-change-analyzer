"""
Impact Analyzer — story + derive-on-read snapshots -> candidate Change Set.

Flow (MVP):
  1. Story arrives as workflow input (manual paste), carrying:
        story id, title, description, stream (PM|VoC), target_branch (e.g. PM_Sep).
  2. Extract candidate search terms from the story (cheap, deterministic).
  3. Derive-on-read: read every registry repo IN THE STORY'S STREAM, each at
     the story's target_branch.
  4. Reasoning backend (mock | copilot) turns (story + snapshots) into the
     Change Set: provider, consumers, dependencies, contract_change,
     confidence, evidence.
  5. Emit a PROPOSED Change Set for human approval.

Branch model (BCBSM): work happens on monthly dev branches (target_branch).
The harness cuts feature/<story>-<slug> from target_branch and PRs back to it.
The registry no longer holds a branch; target_branch is per-run story input.
"""

from __future__ import annotations

import re

from registry import ServiceRegistry
from repo_reader import RepoReader
from reasoning import get_reasoner
from naming import feature_branch

# --- lightweight, deterministic term extraction ----------------------
_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "for", "on", "with",
    "add", "support", "retrieve", "retrieving", "display", "through", "via",
    "member", "s", "it", "their", "this", "that", "as", "be", "is", "are",
}


def extract_terms(story_text: str, max_terms: int = 8) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", story_text.lower())
    seen, terms = set(), []
    for w in words:
        if w in _STOPWORDS or w in seen:
            continue
        seen.add(w)
        terms.append(w)
        if len(terms) >= max_terms:
            break
    return terms


def build_prompt(story: dict, snapshots: list) -> str:
    repo_blocks = []
    for s in snapshots:
        contract = (s.contract_text[:2000] + " ...[truncated]") \
            if s.contract_text and len(s.contract_text) > 2000 \
            else (s.contract_text or "(no contract file at ref)")
        hits = ", ".join(f"{k}: {v}" for k, v in s.code_hits.items()) or "(none)"
        repo_blocks.append(
            f"### repo: {s.name}  (ref: {s.ref})\n"
            f"contract_path: {s.contract_path}\n"
            f"contract_present: {s.contract_found}\n"
            f"code_signals: {hits}\n"
            f"contract_excerpt:\n{contract}\n"
        )
    repos_section = "\n".join(repo_blocks)

    return f"""You are the Impact Analyzer for a cross-repo AI-SDLC harness.
Given a business story and read-only snapshots of candidate repositories
(each read at the story's target development branch), determine the cross-repo
impact.

RULES:
- The PROVIDER is the repo that OWNS the interface/contract being changed.
- CONSUMERS are repos that must adapt to that contract change.
- Use the contract_excerpt and code_signals as evidence. If a repo references
  the area but shows no use of the impacted interface, list it under
  potentially_affected (NOT consumers).
- If evidence is weak or ambiguous, LOWER the confidence score.
- Output STRICT JSON only. No prose, no markdown, no code fences.

STORY:
id: {story.get('story')}
title: {story.get('title')}
description: {story.get('description')}
stream: {story.get('stream')}
target_branch: {story.get('target_branch')}

CANDIDATE REPOSITORIES (stream {story.get('stream')}):
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
    stream = story.get("stream")
    target_branch = story.get("target_branch")
    if not target_branch:
        raise ValueError("story.target_branch is required (e.g. PM_Sep)")

    reg = ServiceRegistry.load(registry_path)
    reader = RepoReader(owner=owner)
    reasoner = reasoner or get_reasoner()
    terms = extract_terms(
        f"{story.get('title', '')} {story.get('description', '')}"
    )

    snapshots, analyzed_refs = [], {}
    for entry in reg.all(stream=stream):
        snap = reader.read(entry.name, target_branch,
                           entry.contract_path, terms)
        snapshots.append(snap)
        analyzed_refs[entry.name] = target_branch

    prompt = build_prompt(story, snapshots)
    result = reasoner(prompt)
    if isinstance(result, str):
        from reasoning import parse_json
        result = parse_json(result)

    return {
        "change_set": {
            "story": story.get("story"),
            "title": story.get("title", ""),
            "stream": stream,
            "target_branch": target_branch,
            "description": story.get("description", ""),
            "feature_branch": feature_branch(story.get("story"),
                                             story.get("title", "")),
            "status": "PROPOSED",
            "analysis": {
                "engine": "copilot-sdk",
                "confidence": result.get("confidence", 0),
                "analyzed_refs": analyzed_refs,
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
