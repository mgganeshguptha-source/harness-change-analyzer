# Forward requested currency through inventory pricing

Inventory-service must consume the updated `api/pricing.yaml` contract from pricing-service and pass the requested currency through when computing the effective price for a book.

**What this repo must change**
- Update inventory-service to accept the currency value provided by the caller/path/query used for pricing.
- Forward that currency to pricing-service when resolving price data.
- Compute and return the effective price using the requested currency, without changing the default behavior when no currency is provided.

**Acceptance criteria**
- Inventory-service consumes the changed `api/pricing.yaml` contract from pricing-service.
- Requested currency is forwarded end-to-end in inventory-service price resolution.
- Effective price returned by inventory-service uses the requested currency.
- If no currency is provided, inventory-service continues to default to USD.