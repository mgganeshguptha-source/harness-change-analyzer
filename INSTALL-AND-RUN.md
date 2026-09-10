# INSTALL & RUN — Harness Change Analyzer

Turns a story into a human-approved execution plan for SDLC-Harness. Two commands:
**analyze** (story -> change set) and **plan** (approved change set -> per-repo
stories + PLAN.md). A developer then runs SDLC-Harness manually per repo.

---

## 0. Prerequisites
- Python 3.11+
- `pip install -r requirements.txt`  (core needs only PyYAML)
- Real analysis / real per-repo stories: Copilot SDK installed + Copilot CLI
  authed (same as the engine). Mock needs nothing extra.
- A token with READ access to candidate repos (for derive-on-read).

## 1. Install
```bash
cd harness-change-analyzer
pip install -r requirements.txt
python tests/tests.py           # expect: 21 passed, 0 failed
```

## 2. Configure the registry
Edit `config/service-registry.yaml`: list every repo with `stream` (PM|VoC),
`stack`, `contract_path`. No branch here — the branch is per-story input.

## 3. Author the story (PoC — repo folder)
> **PoC STOPGAP — flagged for change before wider rollout.** Story lives in a
> folder committed to this repo (clone/push/PR/merge to submit). Swappable to
> SharePoint Graph / JIRA later via the story_provider seam.

`stories/BCBSM-1234/story.md`:
```markdown
---
story: BCBSM-1234
title: Add loyaltyTier to member profile
stream: PM
target_branch: PM_Sep
---
Full description, any length. Acceptance criteria, notes.
```
Optional `stories/BCBSM-1234/attachments/` — text files fed to reasoning; others
listed by name. (PDF/docx/image extraction is backlogged.)

## 4. Analyze -> PROPOSED change set
```bash
cd impact_analysis
HARNESS_REASONING=mock python run.py analyze \
  --story-id BCBSM-1234 \
  --story-source repo --stories-root ../stories \
  --owner YOUR-GH-ORG \
  --registry ../config/service-registry.yaml \
  --out ../change-sets/BCBSM-1234.changeset.yaml
```
Stream + target_branch come from the story frontmatter, not the command line.

## 5. Approve (human)
Open `../change-sets/BCBSM-1234.changeset.yaml`, review provider / consumers /
potentially_affected, edit if needed, then set `status: APPROVED`.

## 6. Plan -> per-repo stories + PLAN.md
```bash
python run.py plan \
  --change-set ../change-sets/BCBSM-1234.changeset.yaml \
  --registry ../config/service-registry.yaml \
  --stories-root ../stories
```
Writes under `stories/BCBSM-1234/per-repo/`:
- `<repo>.md` — AI-drafted per-repo story (scoped to each repo's role).
- `PLAN.md` — repos, dependency order, exact SDLC-Harness run instructions
  (`feature_id`, `base`), and a "run after <dep>'s PR is merged into <base>"
  note only where a dependency edge exists.

## 7. Execute (developer/lead, manual)
For each repo in PLAN.md order:
1. Put that repo's per-repo story where its SDLC-Harness expects the story.
2. Actions -> SDLC-Harness -> Run workflow.
3. Set `feature_id` = the story id, `base` = the target dev branch (e.g. PM_Sep).
4. Review the PR; merge into `base`.
Run a dependent repo only after its dependency's PR is merged into `base` — the
harness checks out `base` and cannot see an unmerged upstream change.

---

## Real AI
Add `--reasoning copilot` (or `HARNESS_REASONING=copilot`) to analyze and plan.
Needs the Copilot SDK + CLI auth (or COPILOT_GITHUB_TOKEN in CI). Model defaults
to gpt-4.1 (override HARNESS_ANALYSIS_MODEL).

## Verified vs. environment-dependent
Verified locally (21 tests): registry/stream filter, change-set validation,
story provider, plan generation with dependency ordering.
Needs your environment: real repos + target_branch reachable by the token; the
Copilot SDK for real analysis and per-repo stories.

## Backlog (revisit after end-to-end)
- Attachment extraction (PDF/docx text) + image understanding (OCR/vision).
- JIRA fetch (Option B) + SharePoint Graph provider (replace the repo-folder PoC).
- Phase 2: auto-orchestration (kept aside in phase2-orchestration).
