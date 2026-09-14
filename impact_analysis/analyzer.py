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

import os
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


def build_prompt(story: dict, candidates: list, code_evidence: list = None,
                 change_type: dict = None) -> str:
    blocks = []
    for s in candidates:
        blocks.append(
            f"### repo: {s.name}  (ref: {s.ref})\n"
            f"contracts_found: {s.contract_found}\n"
            f"contract_content:\n{s.combined_text()}\n"
        )
    repos_section = "\n".join(blocks)

    evidence_section = ""
    if code_evidence:
        lines = ["", "CODE-SIGNAL EVIDENCE (how consumers call providers, from",
                 "shallow-clone + grep at the analysis branch):"]
        for e in code_evidence:
            lines.append(
                f"- {e['consumer']} -> {e['provider']}: {e['kind']} "
                f"'{e['matched']}' ({e['file']}:{e['line']})")
        evidence_section = "\n".join(lines)

    ct_section = ""
    if change_type:
        ct_section = (
            f"\nCHANGE-TYPE (deterministic pre-classification): "
            f"{change_type.get('change_type')} "
            f"(behavioural={change_type.get('behavioural')}).\n"
            f"{change_type.get('reason','')}\n"
            "If behavioural, a provider's value semantics may change WITHOUT an "
            "API-shape change — do not rely on contract diff alone; use the "
            "code-signal evidence and lower confidence if the impact can't be "
            "confirmed from shape.")
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
- CLARIFICATIONS: compare the STORY against the contracts and code-signal
  evidence. List ONLY questions that genuinely BLOCK a confident cross-repo
  answer — e.g. the story implies a field/parameter the contract doesn't have,
  it's unclear which of several consumers is in scope, or breaking-vs-additive
  is ambiguous. Ask grounded, specific questions (reference the contract/repo),
  not generic ones. If there is nothing blocking, return an empty list.
- ASSUMPTIONS: for NON-blocking gaps, proceed using a reasonable assumption and
  record it explicitly in "assumptions" (do not ask about these). Never bury an
  assumption silently.
- Output STRICT JSON only. No prose, no markdown, no code fences.

STORY:
id: {story.get('story')}
title: {story.get('title')}
description: {story.get('description')}

CANDIDATE REPOSITORIES:
{repos_section}
{evidence_section}
{ct_section}

Return JSON with EXACTLY this shape:
{{
  "provider": {{"repo": "", "contract": "", "contract_version": ""}},
  "consumers": [{{"repo": "", "evidence": ""}}],
  "potentially_affected": [{{"repo": "", "reason": ""}}],
  "dependencies": [{{"from": "", "to": ""}}],
  "contract_change": {{"type": "backward_compatible|breaking|unknown"}},
  "confidence": 0,
  "clarifications_needed": ["grounded blocking question strings"],
  "assumptions": ["explicit assumption strings for non-blocking gaps"],
  "evidence": ["short bullet strings"]
}}"""


def analyze(story: dict, registry_path: str, owner: str,
            reasoner=None, debug_path: str | None = None) -> dict:
    from debug_trace import DebugTracer
    dbg = DebugTracer(enabled=bool(story.get("debug")), file_path=debug_path)

    branch_default = story.get("branch_default")
    if not branch_default:
        raise ValueError("story.branch_default is required "
                         "(from analysis_target_branch.yaml)")
    branch_overrides = story.get("branch_overrides", {}) or {}

    reg = ServiceRegistry.load(registry_path)
    reader = RepoReader(owner=owner)
    reasoner = reasoner or get_reasoner()

    dbg.stage("1. STORY PARSE — extract search terms")
    dbg.line("story", story.get("story"))
    dbg.line("title", story.get("title"))
    dbg.block("description (as sent)", story.get("description", "")[:1500])
    terms = extract_terms(
        f"{story.get('title', '')} {story.get('description', '')}")
    dbg.list_("extracted terms", terms)

    # classify the change type (deterministic) — drives widening + flagging
    from change_type import classify
    ct = classify(story)
    dbg.stage("2. CHANGE-TYPE CLASSIFICATION (deterministic, no LLM)")
    dbg.line("change_type", ct["change_type"])
    dbg.line("behavioural", ct["behavioural"])
    dbg.line("contract_only_insufficient", ct["contract_only_insufficient"])
    dbg.kv("keyword scores", ct["scores"])
    dbg.line("reason", ct["reason"])

    entries = reg.all()
    # per-repo resolved branch: override if given, else default
    repo_branch = {e.name: branch_overrides.get(e.name, branch_default)
                   for e in entries}
    dbg.stage("3. BRANCH RESOLUTION + EXISTENCE CHECK")
    dbg.kv("resolved branch per repo", repo_branch)

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
        dbg.line("MISSING BRANCHES", missing)
        dbg.close()
        raise ValueError(
            "Analysis aborted — required branches are missing:\n" + lines +
            "\n\nFix analysis_target_branch.yaml (default/overrides) or create "
            "the branches, then re-run.")
    dbg.line("all branches exist", "yes")

    # derive-on-read ALL repos at their resolved branch, in parallel (no LLM)
    def _read(entry):
        return reader.read(entry.name, repo_branch[entry.name],
                           entry.contract_paths)

    snapshots = []
    with ThreadPoolExecutor(max_workers=MAX_READ_WORKERS) as ex:
        for snap in ex.map(_read, entries):
            snapshots.append(snap)
    dbg.stage("4. DERIVE-ON-READ (contracts at each branch, no LLM)")
    for s in snapshots:
        dbg.line(f"{s.name}", f"contracts_found={s.contract_found}, "
                 f"signals={len(s.all_signals)}")

    # lexical shortlist -> candidates (widen if weak OR if the change is
    # behavioural/insufficient — a semantic change may not surface in lexical
    # contract signals, so cast a wider net for the LLM + human to review).
    from shortlist import CAP as _CAP, MIN_CANDIDATES as _MINC
    cap = story.get("cap") or _CAP
    min_candidates = story.get("min_candidates") or _MINC
    sl = shortlist(terms, snapshots, cap=cap, min_candidates=min_candidates)
    widened_by_changetype = False
    if ct["contract_only_insufficient"] and not sl["widened"]:
        # widen to all snapshots so a behavioural ripple isn't filtered out
        sl = {"candidates": list(snapshots), "scored": sl["scored"],
              "widened": True}
        widened_by_changetype = True
    candidates = sl["candidates"]
    analyzed_refs = {s.name: repo_branch[s.name] for s in candidates}
    shortlist_audit = [{"repo": s.name, "score": s.score,
                        "matched": s.matched} for s in sl["scored"]]
    dbg.stage("5. LEXICAL SHORTLIST (term overlap, no LLM)")
    dbg.line("cap", cap)
    dbg.line("min_candidates", min_candidates)
    dbg.list_("scores (all repos)",
              [f"{a['repo']}: {a['score']} {a['matched']}"
               for a in shortlist_audit])
    dbg.line("widened", f"{sl['widened']}"
             f"{' (forced by change-type)' if widened_by_changetype else ''}")
    dbg.list_("candidates -> LLM", [c.name for c in candidates])

    # code-signal scan (shallow clone + grep) over the candidates — deeper
    # evidence of how consumers call providers (WebClient paths, DTO usage,
    # config URLs), attributed to a provider with file + commit SHA.
    code_scans = []
    code_evidence = []
    if os.environ.get("HARNESS_CODE_SCAN", "on").lower() != "off":
        from code_signals import CodeSignalScanner
        scanner = CodeSignalScanner(owner=owner)
        provider_index = CodeSignalScanner.build_provider_index(candidates)
        with ThreadPoolExecutor(max_workers=MAX_READ_WORKERS) as ex:
            futs = {c.name: ex.submit(scanner.scan, c.name,
                                      repo_branch[c.name], provider_index)
                    for c in candidates}
            for name, fut in futs.items():
                try:
                    code_scans.append(fut.result())
                except Exception as e:  # noqa: BLE001
                    pass
        for cs_scan in code_scans:
            for sig in cs_scan.signals:
                if sig.provider:   # only attributed cross-repo edges
                    code_evidence.append({
                        "consumer": cs_scan.repo,
                        "provider": sig.provider,
                        "kind": sig.kind,
                        "matched": sig.matched,
                        "file": sig.file,
                        "line": sig.line,
                        "commit": cs_scan.commit_sha,
                    })
    dbg.stage("6. CODE-SIGNAL SCAN (shallow clone + grep, candidates only)")
    dbg.line("scan enabled",
             os.environ.get("HARNESS_CODE_SCAN", "on").lower() != "off")
    dbg.list_("attributed edges",
              [f"{e['consumer']} -> {e['provider']}: {e['kind']} "
               f"'{e['matched']}' ({e['file']}:{e['line']})"
               for e in code_evidence])

    # reason over candidates only (contract snapshots + code-signal evidence)
    prompt = build_prompt(story, candidates, code_evidence, ct)
    model = story.get("model")
    dbg.stage("7. LLM REASONING (Copilot)")
    dbg.line("model", model or "default")
    dbg.block("FULL PROMPT", prompt)
    result = reasoner(prompt, model) if model else reasoner(prompt)
    if isinstance(result, str):
        from reasoning import parse_json
        result = parse_json(result)
    import json as _json
    dbg.block("FULL RESPONSE (parsed)", _json.dumps(result, indent=2))

    # ---- clarification gate (Option B) ----
    clarifications = result.get("clarifications_needed", []) or []
    assumptions = result.get("assumptions", []) or []
    confidence = result.get("confidence", 0)
    # normalise: some backends return 0-100, the gate works on 0-1
    if isinstance(confidence, (int, float)) and confidence > 1:
        confidence = confidence / 100.0
    threshold = story.get("clarify_threshold")
    if threshold is None:
        threshold = 0.7
    needs_clarification = bool(clarifications) or confidence < threshold
    status = "NEEDS_CLARIFICATION" if needs_clarification else "PROPOSED"

    dbg.stage("8. CLARIFICATION GATE")
    dbg.line("confidence", confidence)
    dbg.line("threshold", threshold)
    dbg.list_("clarifications_needed", clarifications)
    dbg.list_("assumptions", assumptions)
    dbg.line("status", status)
    dbg.close()

    return {
        "change_set": {
            "story": story.get("story"),
            "title": story.get("title", ""),
            "branch_default": branch_default,
            "branch_overrides": branch_overrides,
            "description": story.get("description", ""),
            "feature_branch": feature_branch(story.get("story"),
                                             story.get("title", "")),
            "status": status,
            "analysis": {
                "engine": "copilot-sdk",
                "model": story.get("model") or "default",
                "confidence": confidence,
                "clarify_threshold": threshold,
                "clarifications_needed": clarifications,
                "assumptions": assumptions,
                "analyzed_refs": analyzed_refs,
                "all_repo_refs": repo_branch,
                "shortlist_widened": sl["widened"],
                "shortlist_cap": cap,
                "shortlist_min_candidates": min_candidates,
                "shortlist_scores": shortlist_audit,
                "change_type": ct["change_type"],
                "behavioural": ct["behavioural"],
                "contract_only_insufficient": ct["contract_only_insufficient"],
                "change_type_reason": ct["reason"],
                "code_signal_evidence": code_evidence,
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
