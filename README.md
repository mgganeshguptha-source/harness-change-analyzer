# Harness Change Analyzer

Repository-neutral layer that turns a JIRA story into a **validated, human-approved
execution plan** for the existing per-repo SDLC-Harness. It analyzes impact and
produces a plan; a developer/lead then runs SDLC-Harness manually per repo. The
engine and service repos are unchanged.

```
JIRA story (PoC: story folder)      # stories/<id>/story.md (frontmatter + prose)
  -> analyze     (human-triggered, READ-ONLY)
       stream filter + derive-on-read (read each repo at target_branch)
       Copilot SDK reasoning (or mock) -> PROPOSED change set
  -> human approval    (confirm/edit blast radius; set status: APPROVED)
  -> plan
       per-repo AI-drafted user stories  stories/<id>/per-repo/<repo>.md
       execution plan                    stories/<id>/per-repo/PLAN.md
         (repos, dependency order, exact SDLC-Harness run instructions)
  -> developer runs SDLC-Harness manually per repo, in the plan's order
```

## Two-phase model (why manual execution)
Auto-orchestration across repos (run provider, gate, release consumers, resume a
failed repo mid-chain) is real distributed-coordination complexity. Phase 1
deliberately stops at a **plan** and hands execution to a human, who runs each
repo's harness using the engine's own (already solid) per-repo resume. The
orchestration code is kept aside (see phase2-orchestration) for if/when manual
sequencing proves too costly at scale.

## Derive-on-read
Dependencies are derived at read time from each repo's contract + code signals,
read at the story's target_branch. No stored dependency graph to drift against.

## Layout
```
config/service-registry.yaml   repo universe (stream, stack, contract path)  EDIT
impact_analysis/
  registry.py        loader + stream filter
  repo_reader.py     derive-on-read (GitHub API, READ ONLY)
  reasoning.py       reasoning backends: mock | copilot
  story_provider.py  story source (PoC: repo folder; SharePoint/JIRA later)
  naming.py          feature/<story>-<slug> naming
  analyzer.py        story + snapshots -> change set
  change_set.py      change-set validation
  plan.py            per-repo stories + execution PLAN.md
  run.py             CLI: analyze | plan
schemas/             change-set shape (doc)
stories/             story folders + generated per-repo/ output
tests/tests.py       Phase-1 plumbing tests (no SDK/network/credits)
```

## Start here
Read INSTALL-AND-RUN.md. Quick check:
```bash
pip install -r requirements.txt
python tests/tests.py     # expect: 21 passed, 0 failed
```

## Commands
```bash
# 1. analyze story -> PROPOSED change set
python impact_analysis/run.py analyze --story-id BCBSM-1234 \
  --story-source repo --stories-root stories \
  --owner YOUR-GH-ORG --registry config/service-registry.yaml \
  --out change-sets/BCBSM-1234.changeset.yaml

# 2. edit change set: set status: APPROVED  (human)

# 3. plan -> per-repo stories + PLAN.md
python impact_analysis/run.py plan \
  --change-set change-sets/BCBSM-1234.changeset.yaml \
  --registry config/service-registry.yaml \
  --stories-root stories
```

Add `--reasoning copilot` to either command for real AI (needs Copilot SDK + auth).
