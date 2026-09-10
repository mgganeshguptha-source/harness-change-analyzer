"""
naming.py — feature branch naming, shared by analyzer + orchestrator.

BCBSM convention: feature/BCBSM-<id>-<slug>, slug derived from the story title.
The <id> is the numeric/suffix part of the story key (BCBSM-1234 -> 1234), but
we keep the full story id in the branch for traceability: feature/<story>-<slug>.
"""

from __future__ import annotations

import re

_MAX_SLUG_WORDS = 6
_MAX_SLUG_LEN = 40


def slugify(title: str) -> str:
    """'Add loyaltyTier to member profile' -> 'add-loyaltytier-to-member'."""
    if not title:
        return ""
    # split camelCase into words, then lowercase everything
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", title)
    words = re.findall(r"[A-Za-z0-9]+", spaced.lower())
    words = words[:_MAX_SLUG_WORDS]
    slug = "-".join(words)
    return slug[:_MAX_SLUG_LEN].rstrip("-")


def feature_branch(story: str, title: str) -> str:
    """feature/BCBSM-1234-add-loyaltytier-to-member."""
    slug = slugify(title)
    return f"feature/{story}-{slug}" if slug else f"feature/{story}"
