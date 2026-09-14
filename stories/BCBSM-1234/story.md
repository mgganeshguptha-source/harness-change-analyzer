---
story: BCBSM-2001
title: Add currency selection to book pricing
---
Allow a book's price to be requested and returned in a chosen currency.
pricing-service adds a currency to its price response so prices can be returned
in a requested currency. inventory-service must pass the requested currency
through when computing the effective price, and book-service must accept a
currency parameter and surface the final price in that currency.

Acceptance criteria:
- pricing-service returns the price in the requested currency.
- inventory-service forwards the requested currency and computes the effective
  price in it.
- book-service accepts a currency parameter and shows the final price in it.
- Existing behaviour (no currency requested) defaults to USD.
