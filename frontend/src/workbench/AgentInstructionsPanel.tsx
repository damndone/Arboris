// v1.9.0 — what the Agent reads at the start of every conversation: the
// built-in analysis guide (read-only), the person's own AGENTS.md (all
// projects) and this project's AGENTS.md. Saved files take effect in the next
// new conversation.

import { useEffect, useState } from "react";
import { draftAgentInstructions, getAgentInstructions, saveAgentInstructions } from "./agent/agentApi";
import type { ResponseOf } from "../apiTypes";
import "./agentInstructions.css";

type View = ResponseOf<"/agent/instructions", "get">;
type Kind = "project" | "personal" | "guide";

const TABS: Array<{ kind: Kind; label: string; hint: string }> = [
  { kind: "project", label: "This project", hint: "The study: question, data, variables, agreed methods. Also read by Codex, Claude Code and pi in this folder." },
  { kind: "personal", label: "Personal", hint: "You, in every project: language, reporting style, conventions. The project's file wins where they differ." },
  { kind: "guide", label: "Built-in guide", hint: "Principles that hold for any analysis, from a regression to forecasting, strategies and machine learning. Read-only." },
];

const message = (reason: unknown) => (reason instanceof Error ? reason.message : String(reason));

export function AgentInstructionsPanel({ projectRoot }: { projectRoot: string }) {
  const [view, setView] = useState<View | null>(null);
  const [kind, setKind] = useState<Kind>("project");
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [replaceWith, setReplaceWith] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  const load = (next: View) => {
    setView(next);
    setTexts(Object.fromEntries(next.layers.map((layer) => [layer.kind, layer.content])));
  };

  useEffect(() => {
    let live = true;
    getAgentInstructions(projectRoot).then((next) => live && load(next)).catch((reason) => live && setError(message(reason)));
    return () => {
      live = false;
    };
  }, [projectRoot]);

  if (!view) return <p className="ai-panel__status">{error || "Loading instructions…"}</p>;
  const layer = view.layers.find((item) => item.kind === kind)!;
  const text = texts[kind] ?? "";
  const changed = text !== layer.content;
  const bytes = new TextEncoder().encode(text).length;
  const tooLarge = bytes > view.limit_bytes;
  const tab = TABS.find((item) => item.kind === kind)!;

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setStatus("");
    try {
      await action();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  };
  const put = (value: string) => setTexts((old) => ({ ...old, [kind]: value }));
  const offer = (value: string) => (text.trim() ? setReplaceWith(value) : put(value));

  return (
    <section className="ai-panel" aria-label="Agent instructions">
      <p className="ai-panel__lead">
        The Agent reads these at the start of every new conversation, general to specific; the more specific one wins where they disagree.
      </p>
      <div className="ai-panel__tabs" role="tablist" aria-label="Instruction layers">
        {TABS.map((item) => {
          const present = view.layers.find((entry) => entry.kind === item.kind)?.exists;
          return (
            <button key={item.kind} type="button" role="tab" aria-selected={kind === item.kind} onClick={() => { setKind(item.kind); setReplaceWith(null); }}>
              {item.label}
              <span className="ai-panel__state">{present ? "in use" : "empty"}</span>
            </button>
          );
        })}
      </div>
      <p className="ai-panel__hint">{tab.hint}</p>
      <p className="ai-panel__path"><code>{layer.path}</code></p>
      <textarea
        aria-label={`${tab.label} instructions`}
        className="ai-panel__text"
        value={text}
        readOnly={!layer.editable}
        rows={18}
        spellCheck={false}
        placeholder={layer.editable ? "Nothing yet. Start from the template, or write your own." : undefined}
        onChange={(event) => put(event.target.value)}
      />
      {replaceWith !== null && (
        <div className="ai-panel__confirm" role="alertdialog" aria-label="Replace the text">
          <span>Replace what is in the editor with this?</span>
          <button type="button" onClick={() => { put(replaceWith); setReplaceWith(null); }}>Replace</button>
          <button type="button" onClick={() => setReplaceWith(null)}>Keep mine</button>
        </div>
      )}
      {layer.editable && (
        <div className="ai-panel__actions">
          <span className={tooLarge ? "ai-panel__size ai-panel__size--over" : "ai-panel__size"}>
            {(bytes / 1024).toFixed(1)} of {view.limit_bytes / 1024} KiB
          </span>
          <span className="ai-panel__spacer" />
          <button type="button" disabled={busy} onClick={() => offer(view.templates[kind] ?? "")}>Start from template</button>
          {kind === "project" && (
            <button type="button" disabled={busy} onClick={() => void run(async () => offer((await draftAgentInstructions(projectRoot)).content))}>
              Draft from this project
            </button>
          )}
          <button
            type="button"
            className="ai-panel__primary"
            disabled={busy || !changed || tooLarge}
            onClick={() => void run(async () => {
              load(await saveAgentInstructions(projectRoot, { kind: kind as "personal" | "project", content: text }));
              setStatus("Saved. New conversations will read it.");
            })}
          >
            Save
          </button>
        </div>
      )}
      {status && <p className="ai-panel__status" role="status">{status}</p>}
      {error && <p className="ai-panel__error" role="alert">{error}</p>}
    </section>
  );
}
