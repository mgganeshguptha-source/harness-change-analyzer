# book-service: reflect PLATINUM-adjusted finalPrice from pricing contract

book-service must consume the updated `api/pricing.yaml` contract from the provider and map the returned pricing data into `finalPrice` without changing behavior for existing tiers. Any book views, responses, or calculations that surface price must use the provider’s updated value as-is.

**Acceptance criteria**
- book-service consumes the changed `api/pricing.yaml` contract from the provider.
- book-service correctly surfaces `finalPrice` for requests that resolve to STANDARD, PREMIUM, or PLATINUM tiers.
- Existing tier handling remains unchanged for STANDARD and PREMIUM.