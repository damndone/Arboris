// v1.9.0 — a conversation as turns: your message, the work the Agent did
// (tool calls and its notes between them), any draft the number check
// withdrew, and the reply. A step or draft that says the same as the reply
// is not shown twice (user review 3: the last reasoning step repeated it).

import type { AgentMessage } from "../agentTypes";

export type Turn = {
  id: string;
  user: AgentMessage | null;
  steps: AgentMessage[];
  /** Answers the number check withdrew before the reply was rewritten. */
  drafts: AgentMessage[];
  responses: AgentMessage[];
  /** Seconds from your message to the Agent's last entry. */
  seconds: number | null;
  /** Where the earlier conversation was summarized (a turn of its own). */
  summary?: AgentMessage;
};

const normal = (text: string) => text.replace(/\s+/g, " ").trim();

/** True when `a` adds nothing to `b`: the same text, or contained in it. */
function repeats(a: string, b: string): boolean {
  const x = normal(a);
  const y = normal(b);
  if (!x || !y) return false;
  return x === y || (x.length >= 40 && y.includes(x));
}

function isStep(message: AgentMessage): boolean {
  return message.role === "tool" || message.stop_reason === "tool_calls";
}

function finish(turn: Turn & { last: AgentMessage | null }): Turn {
  const replies = turn.responses.map((response) => response.content);
  const steps = turn.steps.filter(
    (step) => step.role === "tool" || (step.content.trim() && !replies.some((reply) => repeats(step.content, reply))),
  );
  const drafts = turn.drafts.filter((draft) => !replies.some((reply) => repeats(draft.content, reply)));
  const start = turn.user?.at ? Date.parse(turn.user.at) : NaN;
  const end = turn.last?.at ? Date.parse(turn.last.at) : NaN;
  const seconds = Number.isFinite(start) && Number.isFinite(end) && end >= start && turn.last !== turn.user ? Math.round((end - start) / 1000) : null;
  return { id: turn.id, user: turn.user, steps, drafts, responses: turn.responses, seconds };
}

export function buildTurns(messages: AgentMessage[]): Turn[] {
  const turns: Turn[] = [];
  let current: (Turn & { last: AgentMessage | null }) | null = null;
  const open = (user: AgentMessage | null, index: number) => {
    if (current) turns.push(finish(current));
    current = { id: user?.entry_id ?? `orphan-${index}`, user, steps: [], drafts: [], responses: [], seconds: null, last: user };
  };
  messages.forEach((message, index) => {
    if (message.role === "user") return open(message, index);
    if (message.role === "summary") {
      if (current) turns.push(finish(current));
      current = null;
      turns.push({ id: message.entry_id, user: null, steps: [], drafts: [], responses: [], seconds: null, summary: message });
      return;
    }
    if (!current) open(null, index);
    const turn = current!;
    turn.last = message;
    if (isStep(message)) turn.steps.push(message);
    else if (message.stop_reason === "revised") turn.drafts.push(message);
    else turn.responses.push(message);
  });
  if (current) turns.push(finish(current));
  return turns;
}

const timeFormat = new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const dayFormat = new Intl.DateTimeFormat("en", { month: "short", day: "numeric" });

/** "14:05", or "Oct 13, 14:05" for another day. */
export function messageTime(at: string | undefined, now = new Date()): string {
  if (!at) return "";
  const date = new Date(at);
  if (Number.isNaN(date.getTime())) return "";
  const sameDay = date.toDateString() === now.toDateString();
  return sameDay ? timeFormat.format(date) : `${dayFormat.format(date)}, ${timeFormat.format(date)}`;
}

export function duration(seconds: number | null): string {
  if (seconds === null) return "";
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} min ${seconds % 60} s`;
}

/** A short title for a pinned chapter: the message's first line, trimmed. */
export function chapterTitle(content: string): string {
  const line = content.split("\n").map((part) => part.replace(/^[#>*\-\s]+/, "").trim()).find(Boolean) ?? "Chapter";
  return line.length > 60 ? `${line.slice(0, 57)}…` : line;
}
