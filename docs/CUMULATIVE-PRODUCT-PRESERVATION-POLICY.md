# Cumulative Product Preservation Policy — Machine-Enforced

- Frozen source baseline: `5.2.1-client-admin-correction-po1`
- Frozen artifact SHA-256: `2c528badcf90c1683d68f45a59d5d5004cc82cf3ed1d8d4bd1c4fb901b6fc22f`
- Candidate: `5.2.1-client-admin-correction-po1`

This candidate is additive by default. A capability present in the frozen baseline may not be silently removed merely because a later scope does not mention it. The executable gate in `qa/cumulative_product_preservation.py` verifies that baseline source files remain present and that objective capability evidence from the accepted product remains in the candidate. The unified workspace does not bypass backend authorization or tenant isolation.
