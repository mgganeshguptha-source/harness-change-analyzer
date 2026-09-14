# Forward requested currency through effective price calculation

Update `inventory-service` to consume the changed `api/pricing.yaml` contract from the provider and pass the requested currency through when resolving the effective price.

**This repo must change**
- Accept the currency value on the inventory pricing flow.
- Forward that currency unchanged to pricing-service via the updated `api/pricing.yaml` contract.
- Compute and return the effective price in the requested currency.
- Preserve existing behavior by defaulting to USD when no currency is provided.

**Acceptance criteria**
- `inventory-service` uses the updated `api/pricing.yaml` contract from pricing-service.
- The requested currency is forwarded end-to-end in inventory pricing calls.
- Effective price calculations use the requested currency.
- Requests without a currency still resolve in USD.