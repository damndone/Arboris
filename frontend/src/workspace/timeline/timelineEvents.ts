// v1.9.0 — the analysis ledger in reader terms. The ledger records what
// happened as typed events (`run.rerun`, `postestimation.wald`) with a raw
// summary; the timeline and the bottom bar say it as a sentence. The raw
// event stays available under each entry's details.

import type { Schema } from "../../apiTypes";

export type Disclosure = Schema<"AnalysisDisclosure">;
type Entry = Disclosure["entries"][number];

const POSTESTIMATION: Record<string, string> = {
  wald: "Wald test",
  lincom: "Linear combination",
  nlcom: "Nonlinear combination",
  lr: "Likelihood-ratio test",
  margins: "Marginal effects",
};

const SCRIPT_LANGUAGES: Record<string, string> = { stata: "Stata", r: "R", python: "Python" };

function words(text: string): string {
  return text.replace(/[._]/g, " ").trim();
}

/** The fields a rerun changed, from the ledger's recorded patch; null if it cannot be read. */
function rerunChanges(summary: string): string | null {
  try {
    const patch = JSON.parse(summary) as { changes?: Array<{ field_id?: string; old_value?: unknown; new_value?: unknown }> };
    const parts = (patch.changes ?? [])
      .filter((change) => change.field_id)
      .map((change) => `${words(String(change.field_id))} ${String(change.old_value ?? "—")} → ${String(change.new_value ?? "—")}`);
    return parts.length ? parts.join(", ") : null;
  } catch {
    return null;
  }
}

/** A plain summary the ledger wrote for people (not a serialized patch or draft id). */
function readableSummary(summary: string): string | null {
  const text = summary.trim();
  return text && !/^(?:[{[]|draft=)/.test(text) ? text : null;
}

export function describeEvent(entry: Entry): string {
  const [family, action = ""] = entry.what.split(".", 2);
  if (entry.what === "run.submit") return "Ran a new analysis";
  if (entry.what === "run.rerun") {
    const changes = rerunChanges(entry.summary);
    return changes ? `Reran with changes: ${changes}` : "Reran with changes";
  }
  if (family === "postestimation") return POSTESTIMATION[action] ?? `Post-estimation: ${words(action)}`;
  if (entry.what === "export.analysis_script") {
    const language = Object.keys(SCRIPT_LANGUAGES).find((key) => new RegExp(`\\b${key}\\b`, "i").test(entry.summary));
    return language ? `Exported a ${SCRIPT_LANGUAGES[language]} script` : "Exported an analysis script";
  }
  return readableSummary(entry.summary) ?? `${family[0]?.toUpperCase() ?? ""}${words(family).slice(1)}: ${words(action)}`.trim();
}

export function describeWho(who: string): string {
  if (/^(user|ui|manual)$/i.test(who)) return "You";
  if (/^agent/i.test(who)) return "Agent";
  return who;
}

function count(n: number, one: string, many: string): string | null {
  return n > 0 ? `${n} ${n === 1 ? one : many}` : null;
}

/** One line for the folded bottom panel: the last event and what the history holds. */
export function summarizeTimeline(value: Disclosure | null): string {
  if (!value) return "Analysis history";
  const latest = value.entries[value.entries.length - 1];
  const counts = value.counts;
  const parts = [
    latest ? `Last: ${describeEvent(latest)}` : "No events yet",
    count(counts.models, "model", "models"),
    count(counts.inferential_tests, "test", "tests"),
    count(counts.data_changes, "data change", "data changes"),
  ];
  return parts.filter(Boolean).join(" · ");
}
