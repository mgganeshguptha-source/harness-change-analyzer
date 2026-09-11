---
story: BCBSM-1234
title: Add PLATINUM discount tier to pricing
model: GPT-5.4 mini
---
Extend the pricing-service discountTier to support a new PLATINUM tier in
addition to STANDARD and PREMIUM. inventory-service must apply the PLATINUM
tier when computing effectivePrice, and book-service must reflect the resulting
finalPrice. No breaking changes to existing tiers.

Acceptance criteria:
- pricing-service: discountTier enum includes PLATINUM.
- inventory-service: effectivePrice correctly applies PLATINUM.
- book-service: finalPrice reflects the PLATINUM-adjusted price.