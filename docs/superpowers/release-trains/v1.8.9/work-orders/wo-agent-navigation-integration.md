# Work order: Agent navigation integration

1. Migrate test-only durable fixtures to the server-issued proposal capability
   and current operation lifecycle without changing the safety boundary.
2. Make read-only navigation tolerate absent proposal storage as unavailable.
3. Run the affected route/navigation suite, record failures and decisions in
   the formal event stream, and produce a bounded handoff.

Acceptance is limited to the tests named in the objective. It does not prove
browser, provider, cross-process, full-host, release, or production deployment
readiness.
