// The work of a turn, one line per step (design reference: OpenAI Codex, Apache-2.0,
// codex-rs/tui/src/exec_cell/render.rs). Reads in a row fold into one "Explored" line;
// a step opens to its result, head and tail first, the middle on request.

import { Children, useState, type ReactNode } from "react";
import type { AgentMessage } from "../agentTypes";
import { toolTitle, type ToolStep } from "../toolActivity";

const READS = /^(inspect_|list_|read_|search_|check_)/;

export type ActivityItem =
  | { kind: "step"; message: AgentMessage }
  | { kind: "explored"; messages: AgentMessage[] };

const isRead = (message: AgentMessage) => message.role === "tool" && READS.test(message.name ?? "");

/** A thought with no words for the reader travels with the reads around it. */
const isThought = (message: AgentMessage) => message.role === "assistant" && !message.content.trim() && Boolean(message.reasoning?.trim());

export function activityItems(steps: AgentMessage[]): ActivityItem[] {
  const items: ActivityItem[] = [];
  let thoughts: AgentMessage[] = [];
  const settle = () => {
    items.push(...thoughts.map((message): ActivityItem => ({ kind: "step", message })));
    thoughts = [];
  };
  for (const message of steps) {
    if (isThought(message)) {
      thoughts.push(message);
      continue;
    }
    const last = items[items.length - 1];
    if (isRead(message) && last?.kind === "explored") {
      last.messages.push(...thoughts, message);
    } else if (isRead(message) && last?.kind === "step" && isRead(last.message)) {
      items[items.length - 1] = { kind: "explored", messages: [last.message, ...thoughts, message] };
    } else {
      settle();
      items.push({ kind: "step", message });
      continue;
    }
    thoughts = [];
  }
  settle();
  return items;
}

const HEAD = 10;
const TAIL = 3;

export function resultLines(content: string): string[] {
  let shown: unknown = content;
  try {
    const payload = JSON.parse(content) as { ok?: unknown; output?: unknown; error?: unknown; error_details?: unknown };
    shown = payload.ok === false ? payload.error_details ?? payload.error : payload.output ?? payload;
    // The row already says a lone reason.
    if (payload.ok === false && Array.isArray(shown) && shown.length === 1 && Object.keys(shown[0] ?? {}).join() === "message") return [];
  } catch {
    return content.split("\n");
  }
  return (typeof shown === "string" ? shown : JSON.stringify(shown, null, 2) ?? "").split("\n");
}

function ToolResult({ content }: { content: string }) {
  const [whole, setWhole] = useState(false);
  const lines = resultLines(content);
  if (lines.length === 0) return null;
  if (whole || lines.length <= HEAD + TAIL + 1) return <pre className="agt-result">{lines.join("\n")}</pre>;
  return (
    <pre className="agt-result">
      {lines.slice(0, HEAD).join("\n")}{"\n"}
      <button type="button" className="agt-result__more" onClick={() => setWhole(true)}>… +{lines.length - HEAD - TAIL} lines</button>{"\n"}
      {lines.slice(-TAIL).join("\n")}
    </pre>
  );
}

type PlanStep = { title: string; status: string };

/** The plan a step saved, for update_plan; anything else has none. */
export function planSteps(content: string | undefined): PlanStep[] {
  try {
    const steps = (JSON.parse(content ?? "") as { output?: { plan?: { steps?: PlanStep[] } } }).output?.plan?.steps;
    return Array.isArray(steps) ? steps.filter(step => typeof step?.title === "string") : [];
  } catch {
    return [];
  }
}

function PlanChecklist({ steps }: { steps: PlanStep[] }) {
  return (
    <ul className="agt-plan" data-testid="agent-plan-steps">
      {steps.map((step, index) => (
        <li key={index} data-status={step.status}>
          <span aria-hidden="true">{step.status === "done" ? "✔" : step.status === "in_progress" ? "▸" : "□"}</span> {step.title}
        </li>
      ))}
    </ul>
  );
}

/** A step of the work: what it did, on what, how it ended; opens to its result and sources. */
export function ToolStepRow({ step, content, children }: { step: ToolStep; content?: string; children?: ReactNode }) {
  const [open, setOpen] = useState(false);
  const plan = planSteps(content);
  const row = (
    <span className={`wb-agent-step wb-agent-step--${step.state}`}>
      <span className="wb-agent-step__mark" aria-hidden="true">{step.state === "failed" ? "✗" : step.state === "waiting" ? "…" : "✓"}</span>
      <span className="wb-agent-step__text">
        <span className="wb-agent-step__title">{step.title}</span>
        {step.target && <span className="wb-agent-step__target"> {step.target}</span>}
        {step.detail && <span className="wb-agent-step__detail"> — {step.detail}</span>}
      </span>
      {step.seconds !== null && step.seconds >= 1 && <span className="wb-agent-step__time">{Math.round(step.seconds)} s</span>}
    </span>
  );
  if (!content && Children.toArray(children).length === 0) return <div className="wb-agent-terminal-content">{row}</div>;
  return (
    <div className="wb-agent-terminal-content">
      <details className="wb-agent-tool-details" onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary>{row}</summary>
        {open && content && <ToolResult content={content} />}
        {children}
      </details>
      {plan.length > 0 && <PlanChecklist steps={plan} />}
    </div>
  );
}

function ExploredGroup({ messages, live, render }: { messages: AgentMessage[]; live: boolean; render: (message: AgentMessage) => ReactNode }) {
  const reads = messages.filter(isRead);
  const failed = reads.filter((message) => message.content.includes('"ok": false') || message.content.includes('"ok":false')).length;
  const distinct = [...new Set(reads.map((message) => toolTitle(message.name ?? "")))];
  return (
    <details className="agt-explored" data-testid="agent-explored" open={failed > 0 || undefined}>
      <summary>
        <span className={`wb-agent-step wb-agent-step--${failed ? "failed" : "done"}`}>
          <span className="wb-agent-step__mark" aria-hidden="true">{failed ? "✗" : "✓"}</span>
          <span className="wb-agent-step__text">
            <span className="wb-agent-step__title">{live ? "Exploring" : "Explored"}</span>
            <span className="wb-agent-step__target"> {distinct.slice(0, 2).join(", ")}{reads.length > 2 ? ` · ${reads.length} reads` : ""}</span>
          </span>
        </span>
      </summary>
      {messages.map(render)}
    </details>
  );
}

export function ActivityLog({ steps, live, render }: { steps: AgentMessage[]; live: boolean; render: (message: AgentMessage) => ReactNode }) {
  const items = activityItems(steps);
  return (
    <>
      {items.map((item, index) => item.kind === "step"
        ? render(item.message)
        : <ExploredGroup key={item.messages[0].entry_id} messages={item.messages} live={live && index === items.length - 1} render={render} />)}
    </>
  );
}
