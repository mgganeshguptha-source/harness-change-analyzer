# Add PLATINUM support to inventory pricing

Update `inventory-service` to consume the changed `api/pricing.yaml` contract from the provider and apply the new `PLATINUM` discount tier when computing `effectivePrice`. Preserve existing behavior for `STANDARD` and `PREMIUM`.

**Acceptance criteria**
- `inventory-service` consumes the updated `api/pricing.yaml` contract that includes `PLATINUM`.
- `effectivePrice` is computed correctly for `PLATINUM` requests.
- Existing `STANDARD` and `PREMIUM` pricing behavior remains unchanged.
- Contract-driven tests or mappings in this repo are updated to cover the new tier.