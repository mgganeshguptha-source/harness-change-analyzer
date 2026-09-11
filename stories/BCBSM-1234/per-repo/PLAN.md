# Execution Plan — BCBSM-1234

**Story:** Add PLATINUM discount tier to pricing  
**feature_id for every repo:** `BCBSM-1234`

> This plan is produced by harness-change-analyzer (analysis only). A
> developer/lead runs SDLC-Harness **manually** for each repo. Sequencing
> is human-enforced. **You choose the `base`** (the release/dev branch to
> PR into, e.g. PM_Sep) when you run SDLC-Harness — the analyzer does not
> decide it. The branch shown per repo below is only what analysis READ.

## Repos in this change

- **pricing-service** — provider (no dependencies, analyzed at `main`)
- **inventory-service** — consumer (depends on pricing-service, analyzed at `main`)
- **book-service** — potentially_affected (depends on inventory-service, analyzed at `main`)

## Run order

### Step 1: pricing-service  (provider)

- story file: `story-branch/stories/BCBSM-1234/per-repo/pricing-service.md`
- run: SDLC-Harness with `feature_id=BCBSM-1234`, `base=<your target release branch>`
- no upstream dependency — can run immediately

### Step 2: inventory-service  (consumer)

- story file: `story-branch/stories/BCBSM-1234/per-repo/inventory-service.md`
- run: SDLC-Harness with `feature_id=BCBSM-1234`, `base=<your target release branch>`
- ⚠ run only after **pricing-service**'s PR is merged into your base branch

### Step 3: book-service  (potentially_affected)

- story file: `story-branch/stories/BCBSM-1234/per-repo/book-service.md`
- run: SDLC-Harness with `feature_id=BCBSM-1234`, `base=<your target release branch>`
- ⚠ run only after **inventory-service**'s PR is merged into your base branch

## How to run each repo

1. Copy the repo's per-repo story file into that repo's expected story
   location (per your SDLC-Harness setup).
2. In that repo: Actions → **SDLC-Harness** → Run workflow.
3. Set `feature_id = BCBSM-1234` and set `base` to your target
   release/dev branch (e.g. PM_Sep).
4. Review the PR the harness raises; merge into your chosen base.

Where a repo depends on another, run it only **after** the dependency's
PR is merged into your base branch — the harness checks out that base, so
an unmerged upstream change is not visible to it.
