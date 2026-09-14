"""
change_type.py — classify a story's change type from its text (deterministic).

Contract-based analysis is reliable for STRUCTURAL changes (add a field, change
an enum, new endpoint) but weak for BEHAVIOURAL changes (a value is computed
differently while the API shape is unchanged). This module does a cheap,
LLM-free classification of the story to decide whether contract-only evidence
is sufficient, so the analyzer can:
  * WIDEN candidate discovery for behavioural stories, and
  * FLAG "contract-only evidence insufficient — verify functional impact".

The LLM also returns its own change_type during analysis; this deterministic
pass is what drives widening/flagging, and the two are recorded side by side.

Categories:
  contract    - API/schema shape change (field, enum, endpoint, version)
  behaviour   - semantics change with likely-unchanged shape (calc, rule, logic)
  data        - data/schema/storage change
  event       - message/topic/event change
  internal    - change fully inside one service, no interface
  config      - configuration change
  unknown     - can't tell
"""

from __future__ import annotations

import re

# keyword signals per category (lowercased, word-boundary matched)
_SIGNALS = {
    "behaviour": [
        "calculat", "compute", "recompute", "business rule", "rule",
        "eligibil", "validation", "validate", "default behaviour",
        "default behavior", "status", "determination", "logic", "algorithm",
        "semantic", "rounding", "threshold", "formula", "derive", "scoring",
        "priorit", "workflow change", "processing",
    ],
    "contract": [
        "add field", "new field", "add endpoint", "new endpoint", "api",
        "contract", "schema field", "enum", "response", "request",
        "attribute", "property", "version", "openapi", "payload",
    ],
    "data": [
        "database", "table", "column", "migration", "persist", "storage",
        "data model", "entity",
    ],
    "event": [
        "event", "message", "topic", "queue", "publish", "subscribe",
        "kafka", "async",
    ],
    "config": [
        "config", "configuration", "property", "feature flag", "toggle",
        "environment variable", "setting",
    ],
    "internal": [
        "refactor", "internal", "cleanup", "rename variable", "performance",
        "optimi", "tech debt", "logging",
    ],
}


def classify(story: dict) -> dict:
    """
    Returns:
      {
        "change_type": <top category>,
        "scores": {category: hits},
        "behavioural": bool,       # behaviour signal present and significant
        "contract_only_insufficient": bool,   # flag for the plan/human
        "reason": str,
      }
    """
    text = f"{story.get('title','')} {story.get('description','')}".lower()

    scores = {}
    for cat, kws in _SIGNALS.items():
        hits = sum(1 for kw in kws if kw in text)
        if hits:
            scores[cat] = hits

    if not scores:
        return {
            "change_type": "unknown",
            "scores": {},
            "behavioural": False,
            "contract_only_insufficient": True,   # unknown -> be cautious
            "reason": "no clear change-type signal; treat contract evidence as "
                      "insufficient and verify functional impact.",
        }

    top = max(scores, key=scores.get)
    behavioural = scores.get("behaviour", 0) > 0

    # Contract-only evidence is INSUFFICIENT when the story is behavioural (or
    # unknown), because a semantic change may not alter the API shape the
    # analyzer reads.
    insufficient = behavioural or top in ("behaviour", "unknown", "internal")

    if behavioural:
        reason = ("story shows behavioural/semantic signals; a value's meaning "
                  "may change without an API-shape change, so contract-only "
                  "evidence is insufficient — verify functional impact per repo.")
    elif top in ("internal",):
        reason = ("story looks internal to a service; cross-repo contract "
                  "evidence is not the right signal — confirm scope per repo.")
    elif top == "contract":
        reason = "story looks structural (contract/API shape); contract " \
                 "evidence is a strong signal."
    else:
        reason = f"top change-type signal: {top}."

    return {
        "change_type": top,
        "scores": scores,
        "behavioural": behavioural,
        "contract_only_insufficient": insufficient,
        "reason": reason,
    }
