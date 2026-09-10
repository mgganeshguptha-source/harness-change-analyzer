"""
story_provider.py — where story details come from.

*** PoC STOPGAP — MUST CHANGE BEFORE WIDER ROLLOUT ***
The RepoFolderProvider reads the story from a folder committed to the Control
Plane repo. This requires clone/push/PR/merge to submit a story, and a merge
bottleneck. It exists only so the PoC runs on GitHub-hosted runners today,
without SharePoint Graph or JIRA API access (both need org admin approval).

The StoryProvider interface is the seam: later, SharePointGraphProvider or
JiraProvider drop in with NO change to the analyzer. All return the same
StoryInput shape.

Story folder layout (repo stopgap):
    stories/<story-id>/
        story.md          # YAML frontmatter (target_branch, title) + prose body
        attachments/      # optional; text-readable files fed to reasoning, others listed

story.md frontmatter example:
    ---
    story: BCBSM-1234
    title: Add loyaltyTier to member profile
    target_branch: PM_Sep
    ---
    Full description here. Any length. Acceptance criteria, notes, etc.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml

# text-readable attachment types fed into the reasoning prompt; others listed by name
_TEXT_EXTS = {".md", ".txt", ".json", ".yaml", ".yml", ".csv"}
_MAX_ATTACH_BYTES = 20000   # per attachment, to bound prompt size


@dataclass
class StoryInput:
    story: str
    title: str
    description: str
    branch_default: str                       # from analysis_target_branch.yaml
    branch_overrides: dict = field(default_factory=dict)   # repo -> branch
    attachments_text: dict = field(default_factory=dict)   # name -> content
    attachments_listed: list = field(default_factory=list)  # names only (binary)

    def as_story_dict(self) -> dict:
        # description carries prose + any inlined text attachments
        desc = self.description
        if self.attachments_text:
            desc += "\n\n--- ATTACHMENTS ---\n"
            for name, content in self.attachments_text.items():
                desc += f"\n[{name}]\n{content}\n"
        if self.attachments_listed:
            desc += ("\n\n--- ATTACHMENTS (not inlined) ---\n"
                     + ", ".join(self.attachments_listed))
        return {
            "story": self.story,
            "title": self.title,
            "description": desc,
            "branch_default": self.branch_default,
            "branch_overrides": self.branch_overrides,
        }


class StoryProvider:
    """Interface. get(story_id) -> StoryInput."""
    def get(self, story_id: str) -> StoryInput:
        raise NotImplementedError


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split '---\\n<yaml>\\n---\\n<body>' into (meta, body). No frontmatter -> ({}, text)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    meta = yaml.safe_load(text[3:end]) or {}
    body = text[end + 3:].lstrip("\n")
    return (meta if isinstance(meta, dict) else {}), body


class RepoFolderProvider(StoryProvider):
    """
    *** PoC STOPGAP *** Reads stories/<id>/ from the Control Plane repo checkout.
    Replace with SharePointGraphProvider / JiraProvider before wider rollout.
    """
    def __init__(self, stories_root: str = "stories"):
        self.root = stories_root

    def get(self, story_id: str) -> StoryInput:
        folder = os.path.join(self.root, story_id)
        story_md = os.path.join(folder, "story.md")
        if not os.path.exists(story_md):
            raise FileNotFoundError(
                f"story not found: {story_md} "
                f"(create stories/{story_id}/story.md)")

        with open(story_md, "r", encoding="utf-8") as fh:
            meta, body = _parse_frontmatter(fh.read())

        # analysis_target_branch.yaml is REQUIRED (fail fast if absent)
        atb = os.path.join(folder, "analysis_target_branch.yaml")
        if not os.path.exists(atb):
            raise FileNotFoundError(
                f"analysis target branch file not found: {atb} "
                f"(create stories/{story_id}/analysis_target_branch.yaml with a "
                f"'default:' branch and optional per-repo 'overrides:')")
        with open(atb, "r", encoding="utf-8") as fh:
            btree = yaml.safe_load(fh) or {}
        branch_default = btree.get("default")
        branch_overrides = btree.get("overrides", {}) or {}
        if not branch_default:
            raise ValueError(
                f"{atb} must set 'default:' (the branch to analyze repos at "
                f"unless overridden per repo)")

        text_attach, listed = {}, []
        adir = os.path.join(folder, "attachments")
        if os.path.isdir(adir):
            for name in sorted(os.listdir(adir)):
                path = os.path.join(adir, name)
                if not os.path.isfile(path):
                    continue
                ext = os.path.splitext(name)[1].lower()
                if ext in _TEXT_EXTS:
                    with open(path, "r", encoding="utf-8",
                              errors="replace") as fh:
                        content = fh.read(_MAX_ATTACH_BYTES)
                    text_attach[name] = content
                else:
                    listed.append(name)

        return StoryInput(
            story=meta.get("story", story_id),
            title=meta.get("title", ""),
            description=body.strip(),
            branch_default=branch_default,
            branch_overrides=branch_overrides,
            attachments_text=text_attach,
            attachments_listed=listed,
        )


def get_provider(kind: str | None = None, **kwargs) -> StoryProvider:
    """Select a provider. PoC default: repo-folder. Later: sharepoint | jira."""
    kind = (kind or os.environ.get("HARNESS_STORY_SOURCE", "repo")).lower()
    if kind == "repo":
        return RepoFolderProvider(**kwargs)
    # placeholders for the swap-in later:
    # if kind == "sharepoint": return SharePointGraphProvider(**kwargs)
    # if kind == "jira":       return JiraProvider(**kwargs)
    raise ValueError(f"unknown story source: {kind} "
                     f"(PoC supports 'repo'; sharepoint/jira are future)")
