# Add requested currency to pricing API

Update `pricing-service` as the provider of `api/pricing.yaml` so the pricing endpoint accepts a currency request parameter and returns the price in that currency. This repo owns the contract change and must define the request/response shape for currency-aware pricing, including the default behavior when no currency is supplied.

## Acceptance criteria

- `api/pricing.yaml` is updated by `pricing-service` to include a currency input for pricing requests.
- The pricing response includes the price expressed in the requested currency.
- When no currency is requested, the API defaults to USD.
- The contract change is sufficient for downstream consumers to pass through and surface the currency value consistently.