/**
 * PROVISIONAL fixture — see Contract Change Request CCR-C1.
 *
 * Work order C's `consumes` list includes `NotebookPlanningContextV1`'s
 * `budget_report` / `omissions` for the visible slice, and spec §13 requires the
 * trace decision chain to be inspectable. Neither has a canonical mock in
 * `tests/fixtures/contracts/v181/` at contract lock 481fc2e.
 *
 * Rather than block the visible slice — which exists precisely because this
 * project's real defects have been found by live inspection, not by
 * deterministic tests — the lane renders against the shapes written in spec
 * §12.3 and §13.2, using the measured numbers the spec itself calibrated
 * against the v1.8.0 real ARMA-GARCH run (59 artifacts, 36 of them
 * `time_series_json`, ~24 KB bundle budget).
 *
 * When Integration locks `NotebookPlanningContextV1@1.0` and
 * `agent-trace-event/v1` as canonical mocks, this file must be deleted and the
 * tests repointed at those fixtures. It is deliberately named `provisional` so
 * it cannot be mistaken for a locked contract.
 */

import type { NotebookContextSlice } from "../contracts";

export function provisionalContextSlice(): NotebookContextSlice {
  return {
    context_id: "ctx_9c21ab",
    context_profile: "notebook-plan/v1",
    generation_context_hash:
      "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    freshness_dependency_fingerprint:
      "fresh1:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    artifact_type_counts: [
      { artifact_type: "time_series_json", count: 36 },
      { artifact_type: "figure", count: 12 },
      { artifact_type: "table", count: 10 },
      { artifact_type: "model_result", count: 1 },
    ],
    omissions: [
      {
        section: "artifact_summaries",
        included_count: 5,
        available_count: 59,
        reason: "section_budget_exceeded",
        omitted_by_type: [
          { artifact_type: "time_series_json", count: 36 },
          { artifact_type: "figure", count: 11 },
          { artifact_type: "table", count: 7 },
        ],
      },
      {
        section: "bounded_lineage",
        included_count: 10,
        available_count: 11,
        reason: "section_budget_exceeded",
        omitted_by_type: [],
      },
    ],
    budget_report: {
      sections: [
        { section: "analysis_contract", used_bytes: 1024, budget_bytes: 1024 },
        { section: "dataset_profile", used_bytes: 504, budget_bytes: 2765 },
        { section: "active_run_summary", used_bytes: 4096, budget_bytes: 4096 },
        { section: "bounded_lineage", used_bytes: 10_900, budget_bytes: 11_264 },
        { section: "artifact_summaries", used_bytes: 1536, budget_bytes: 4096 },
        { section: "existing_option_summaries", used_bytes: 1420, budget_bytes: 1536 },
      ],
      total_used_bytes: 21_480,
      total_budget_bytes: 24_576,
    },
    source_manifest: [
      {
        source_ref: "analysis_contract:ac_0001",
        revision: 1,
        selection_reason: "analysis contract",
        never_truncated: true,
      },
      {
        source_ref: "run:run-8ffc81c",
        revision: 3,
        selection_reason: "active head",
        never_truncated: false,
      },
      {
        source_ref: "dataset:vix_daily",
        revision: 2,
        selection_reason: "endogenous series source",
        never_truncated: false,
      },
    ],
    trace: [
      {
        event_id: "evt_001",
        sequence: 1,
        event_type: "context.compiled",
        occurred_at: "2026-07-22T16:19:40+00:00",
        summary: "notebook-plan/v1 compiled, 21480 bytes, 2 sections truncated",
      },
      {
        event_id: "evt_002",
        sequence: 2,
        event_type: "agent.plan.requested",
        occurred_at: "2026-07-22T16:19:41+00:00",
        summary: "deepseek-v4-flash, prompt notebook-plan@3, vocabulary ts@1.8.1",
      },
      {
        event_id: "evt_003",
        sequence: 3,
        event_type: "agent.plan.completed",
        occurred_at: "2026-07-22T16:19:58+00:00",
        summary: "3 options generated, 1 rejected by validator",
      },
      {
        event_id: "evt_004",
        sequence: 4,
        event_type: "option.revision.created",
        occurred_at: "2026-07-22T16:20:00+00:00",
        summary: "opt_7f3a1c rev 2, supersedes rev 1",
      },
      {
        event_id: "evt_005",
        sequence: 5,
        event_type: "proposal.validation.completed",
        occurred_at: "2026-07-22T16:20:01+00:00",
        summary: "prop_51de90 rev 1 valid",
      },
      {
        event_id: "evt_006",
        sequence: 6,
        event_type: "user.decision.recorded",
        occurred_at: "2026-07-22T16:21:12+00:00",
        summary: "deferred",
      },
    ],
  };
}
