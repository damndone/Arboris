// v1.9.0 — what you can do with a message, as in Claude: copy it, go back to
// before it (your own messages), continue from it in a new conversation, or
// pin it as a chapter. The time it was written sits beside them.

import { useState } from "react";
import type { AgentMessage } from "../agentTypes";
import { chapterTitle, messageTime } from "./turns";

const Icon = ({ d }: { d: string }) => (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={d} />
  </svg>
);

const COPY = "M5.5 5.5V3.25c0-.55.45-1 1-1h6.25c.55 0 1 .45 1 1V9.5c0 .55-.45 1-1 1H10.5M3.25 5.5H9.5c.55 0 1 .45 1 1v6.25c0 .55-.45 1-1 1H3.25c-.55 0-1-.45-1-1V6.5c0-.55.45-1 1-1Z";
const CHECK = "M3.5 8.5 6.5 11.5 12.5 4.5";
const REWIND = "M3 3.5v3.75h3.75M3.4 7.1A5 5 0 1 1 4.6 11.6";
const FORK = "M5 2.75v4.5M5 7.25c0 2 1.5 2.75 3.5 2.75H11M11 10 9 8M11 10l-2 2M5 13.25v-6";
const PIN = "M10 2.5 13.5 6l-1.5 1.5-1-1-2.5 2.5.5 3-1 1-2.25-2.25L3 13.5M5.75 9.75 3.5 7.5l1-1 3 .5L10 4.5l-1-1Z";

export interface MessageActionsProps {
  message: AgentMessage;
  pinned: boolean;
  busy: boolean;
  onRewind?: (entryId: string) => void;
  onFork?: (entryId: string) => void;
  onPin?: (entryId: string, title: string) => void;
  onUnpin?: (entryId: string) => void;
}

export function MessageActions({ message, pinned, busy, onRewind, onFork, onPin, onUnpin }: MessageActionsProps) {
  const [copied, setCopied] = useState(false);
  // An optimistic entry is not on the server yet; only copying applies.
  const saved = !message.entry_id.startsWith("local-");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="agt-actions" role="toolbar" aria-label="Message actions">
      {message.at && (
        <time dateTime={message.at} title={new Date(message.at).toLocaleString("en")}>
          {messageTime(message.at)}
        </time>
      )}
      <button type="button" aria-label={copied ? "Copied" : "Copy"} title="Copy" onClick={() => void copy()}>
        <Icon d={copied ? CHECK : COPY} />
      </button>
      {saved && message.role === "user" && onRewind && (
        <button
          type="button"
          aria-label="Rewind to here"
          title="Go back to before this message; its text returns to the input. Later turns stay in the log."
          disabled={busy}
          onClick={() => onRewind(message.entry_id)}
        >
          <Icon d={REWIND} />
        </button>
      )}
      {saved && onFork && (
        <button
          type="button"
          aria-label="Fork from here"
          title="Continue in a new conversation from this point; this one stays as it is"
          disabled={busy}
          onClick={() => onFork(message.entry_id)}
        >
          <Icon d={FORK} />
        </button>
      )}
      {saved && (onPin || onUnpin) && (
        <button
          type="button"
          aria-label={pinned ? "Unpin chapter" : "Pin as chapter"}
          aria-pressed={pinned}
          title={pinned ? "Remove this chapter" : "Pin as a chapter you can jump back to"}
          disabled={busy}
          onClick={() => (pinned ? onUnpin?.(message.entry_id) : onPin?.(message.entry_id, chapterTitle(message.content)))}
        >
          <Icon d={PIN} />
        </button>
      )}
    </div>
  );
}
