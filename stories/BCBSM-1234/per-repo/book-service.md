# Book service: accept requested currency and return priced books in that currency

Book-service must consume the updated `api/pricing.yaml` contract from pricing-service and pass a requested currency through to pricing/inventory pricing flow, then surface the final book price in that currency.

**What this repo must change**
- Update book-service request handling to accept an optional `currency` parameter.
- Forward the requested currency through to the pricing/inventory call chain.
- Render the returned final price using the requested currency.
- Keep the existing default behavior unchanged when no currency is provided.

**Acceptance criteria**
- book-service accepts a `currency` parameter on the relevant pricing endpoint/API flow.
- book-service passes the requested currency through to the downstream pricing contract defined by `api/pricing.yaml`.
- book-service shows the final price in the requested currency.
- If no currency is provided, book-service defaults to USD and preserves current behavior.