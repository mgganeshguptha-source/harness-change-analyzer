# Add PLATINUM to pricing contract

**Scope:** Update `pricing-service` as the provider of `api/pricing.yaml` to add a new `PLATINUM` value to `discountTier` while preserving existing `STANDARD` and `PREMIUM` behavior.

**Acceptance criteria:**
- `api/pricing.yaml` includes `PLATINUM` in the `discountTier` enum.
- The contract change is backward-compatible for existing tiers.
- Any generated/validated provider artifacts remain aligned with the updated contract.