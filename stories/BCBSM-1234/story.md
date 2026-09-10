---
story: BCBSM-1234
title: Add loyaltyTier to member profile
target_branch: PM_Sep
---
Expose a member's loyaltyTier through the Member API so the provider search
experience can display it and apply a tier-based discount.

Acceptance criteria:
- Member API returns loyaltyTier on the member profile response.
- Provider search reads loyaltyTier and shows the tier badge.
- Backward compatible: existing consumers unaffected when the field is absent.
