# QPA1 manual acceptance

Use the loopback server at `http://127.0.0.1:8710/admin/` and the prepared
revision-4 EVW at
`C:\Users\artwh\OneDrive\Documents\legal2\.tmp\sfv1-fixture-multicorpus-v15.evw`.

1. Confirm the admin page shows schema v4, the five operations
   `keyword_expansion`, `analysis_planning`, `window_evidence_extraction`,
   `ledger_compaction`, and `ledger_synthesis`, and retrieval mode
   `none|semantic_ranges`.
2. Save a harmless planner or window-setting draft, validate it, activate it,
   and confirm the active version changes without restarting the server.
3. In the Python harness, submit a question. Confirm progress shows planning,
   semantic lookup when selected, windows, evidence validation, optional
   compaction, synthesis, and a terminal result.
4. Inspect a partial-validation fixture or live result. Confirm the visible
   result says `PARTIAL EVIDENCE VALIDATION` and shows the rejected count;
   rejected ranges do not appear in the ledger or findings.
5. For the paid diagnostic only, use the exact QPA1-900 run procedure in
   `09_live_validation.md`; never rerun or switch provider after a failure.

Do not expose the loopback admin port, copy API keys, or modify the EVW.
