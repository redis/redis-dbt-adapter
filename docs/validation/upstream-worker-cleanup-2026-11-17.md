# Native refusal probes with upstream worker cleanup

While syncing the engine fork from upstream main, the new worker-stop callback
began closing parked native connections instead of leaking them. A connection
owning temporary relations may publish their cleanup during CLI shutdown.

On engine merge candidate `39a2172e1b358e0082726c018bdd00eb5d18bb30`, the original
refusal probe completed its SQL row/time-zone/schema/temp-state assertions but
then rejected two successful publications because it expected exactly one. The
second publication is consistent with the newly executed connection teardown;
a global publication count does not identify SQL replay. The observed SQL row
count remained one. The [original counter failure](upstream-worker-cleanup-2026-11-17/initial-counter-failure.log)
is retained without being reported as a write-replay defect.

The corrected probe:

- Requires a refused workspace and a subsequent successful publication, plus
  the existing exact row and session-state assertions.
- Refuses all rebases of exactly 20 native attempt workspaces. A hypothetical
  twenty-first SQL attempt would no longer be refused, so it must fail the
  required refusal/error or persisted-state assertion.
- Explicitly checks the target still has only the original row after exhaustion.
- Retains the script-prefix assertion, which proves the first statement was not
  replayed and the refused second statement did not commit.
- Allows teardown publication after that refusal budget, and keeps publication
  counts visible in receipts. The optional Arrow runtime bounds and one-shot
  protections are unchanged.

Forty-three runner tests pass, including finite-budget/rebase/cleanup coverage.
The candidate also passes 64 engine retry tests, 12 connection tests (including
worker exit and panicking-close handling), native and Flight smoke/parity/auth,
all refusal cases, and same-session cancellation/query-lease settlement with
latest driver main `3671fca7894240551d19aeb196d7b7362f8869d2`.

[Runtime receipt](upstream-worker-cleanup-2026-11-17/engine-validation.json),
[refusal counts](upstream-worker-cleanup-2026-11-17/refusal.json),
[cancellation receipt](upstream-worker-cleanup-2026-11-17/session-cancellation.json),
and [source/log digests](upstream-worker-cleanup-2026-11-17/summary.json) are retained.
Successful native/Flight smoke/parity/auth phases ran before the original
counter assertion; after changing only the probe, the refusal and cancellation
phases were rerun against the same immutable engine commit. The receipt labels
those earlier successful phases explicitly.

This changes qualification tooling, not the integration engine pin or published
support scope. The separate upstream fork sync can include subsequent upstream
commits with additional focused validation; this receipt remains bound to the
candidate named above. All execution recorded here is automation.
