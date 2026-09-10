"""
shortlist.py — narrow all repos to ~10 candidates BEFORE the LLM reasoning call.

Deterministic, no LLM. Scores each repo by term overlap between the story's
extracted terms and the repo's parsed contract signals (paths, operationIds,
tags, schema names). Keeps the top-K by score.

Recall safety (widen-on-weak-match): if too few repos score above zero — i.e.
the story is worded semantically and lexical matching missed — fall back to
ALL repos so a real dependency is never silently dropped. The LLM then reasons
over the wider set, and a human approves. A missed repo (false negative) is the
dangerous failure; extra candidates are cheap.
"""

from __future__ import annotations

from dataclasses import dataclass


CAP = 10               # max candidates sent to the LLM
MIN_CANDIDATES = 3     # if fewer than this score > 0, widen to all


@dataclass
class Scored:
    name: str
    score: int
    matched: list      # which story terms hit this repo (for explainability)


def score_repos(story_terms: list, snapshots: list) -> list:
    """snapshots: list[RepoSnapshot]. Returns Scored, highest first."""
    terms = {t.lower() for t in story_terms if t}
    scored = []
    for snap in snapshots:
        sig = snap.all_signals
        matched = sorted(terms & sig)
        scored.append(Scored(name=snap.name, score=len(matched),
                             matched=matched))
    scored.sort(key=lambda s: (-s.score, s.name))
    return scored


def shortlist(story_terms: list, snapshots: list,
              cap: int = CAP, min_candidates: int = MIN_CANDIDATES) -> dict:
    """
    Returns:
      {
        "candidates": [RepoSnapshot, ...],   # the repos to send to the LLM
        "scored": [Scored, ...],             # all repos with scores (audit)
        "widened": bool,                     # True if we fell back to all repos
      }
    """
    scored = score_repos(story_terms, snapshots)
    by_name = {s.name: s for s in snapshots}

    positive = [s for s in scored if s.score > 0]

    if len(positive) < min_candidates:
        # weak lexical signal — widen to all repos (recall safety)
        candidates = list(snapshots)[:max(cap, len(snapshots))]
        return {"candidates": candidates, "scored": scored, "widened": True}

    top = positive[:cap]
    candidates = [by_name[s.name] for s in top]
    return {"candidates": candidates, "scored": scored, "widened": False}
