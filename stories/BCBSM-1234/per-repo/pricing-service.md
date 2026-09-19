# Add requested-currency support to pricing responses

**Repo scope:** `pricing-service` is the provider and owns `api/pricing.yaml`; update that contract and the service implementation so price requests can specify a currency and responses return the price in that currency.

**What this repo must change**
- Extend `api/pricing.yaml` to accept a currency parameter on the pricing request.
- Update pricing logic to return the computed price in the requested currency.
- Preserve existing behavior when no currency is provided by defaulting to USD.

**Acceptance criteria**
- `api/pricing.yaml` documents the currency request parameter and response shape.
- Pricing responses include the currency used to compute the price.
- A requested currency is honored end-to-end within pricing-service.
- Requests without a currency continue to return USD-priced results.