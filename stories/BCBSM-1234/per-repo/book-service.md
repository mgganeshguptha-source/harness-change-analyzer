# Book service: surface priced books in requested currency

Book service must accept an optional `currency` parameter on the pricing flow, consume the updated `api/pricing.yaml` contract from the provider, and return the final book price in that currency. If no currency is provided, it must preserve existing behavior by defaulting to `USD`.

**Acceptance criteria**
- Book service accepts a `currency` request parameter and passes it through to downstream pricing/inventory calls.
- Book service consumes the updated `api/pricing.yaml` contract from the provider for the currency-aware price response.
- The final response includes the price in the requested currency.
- When no currency is requested, the response remains `USD`-based and existing behavior is unchanged.