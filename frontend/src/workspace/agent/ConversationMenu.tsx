// v1.9.0 — the project's Agent conversations, from the Agent's header: the
// current one's title opens the list (search, switch, rename, archive,
// delete); the pen starts a new one. A node or page continues the
// conversation chosen for it here.

import { useCallback, useEffect, useRef, useState } from "react";
import { useAgentSurfaceOptional } from "../../workbench/agent/AgentSurfaceContext";
import { deleteAgentConversation, listAgentConversations, updateAgentConversation } from "../../workbench/agent/agentApi";
import { messageTime } from "../../workbench/agent/transcript/turns";
import { useProjectRootOptional } from "../../workbench/ProjectRootContext";
import type { ResponseOf } from "../../apiTypes";
import { ChevronIcon, ComposeIcon, MoreIcon } from "../icons";
import "./conversationMenu.css";

type Conversation = ResponseOf<"/agent/conversations", "get">["conversations"][number];

const message = (reason: unknown) => (reason instanceof Error ? reason.message : String(reason));

function firstLine(text: string): string {
  const line = text.split("\n").map((part) => part.replace(/^[#>*\-\s]+/, "").trim()).find(Boolean) ?? "";
  return line.length > 60 ? `${line.slice(0, 59)}…` : line;
}

export function ConversationMenu() {
  const agent = useAgentSurfaceOptional();
  const projectRoot = useProjectRootOptional();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Conversation[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [query, setQuery] = useState("");
  const [actionsFor, setActionsFor] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [error, setError] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const sessionId = agent?.sessionId ?? null;

  const load = useCallback(async () => {
    if (!projectRoot) return;
    try {
      setItems((await listAgentConversations(projectRoot, showArchived)).conversations);
    } catch (reason) {
      setError(message(reason));
    }
  }, [projectRoot, showArchived]);

  // The list (and the current title) follows the conversation shown.
  useEffect(() => {
    void load();
  }, [load, sessionId, open, agent?.messages.length]);

  useEffect(() => {
    if (!open) return undefined;
    const close = (event: Event) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" && !renaming : !root.current?.contains(event.target as Node)) {
        setOpen(false);
        setActionsFor(null);
        setDeleting(null);
      }
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open, renaming]);

  if (!agent || !projectRoot || !agent.openConversation || !agent.newConversation) return null;
  const current = items.find((item) => item.session_id === sessionId);
  const firstQuestion = agent.messages.find((item) => item.role === "user")?.content;
  const label = current?.title ?? (firstQuestion ? firstLine(firstQuestion) : "New conversation");
  const shown = items.filter((item) => {
    const needle = query.trim().toLowerCase();
    return !needle || `${item.title} ${item.about}`.toLowerCase().includes(needle);
  });

  const act = async (run: () => Promise<void>) => {
    setError("");
    try {
      await run();
      await load();
    } catch (reason) {
      setError(message(reason));
    }
  };
  const rename = (id: string, title: string) => act(async () => {
    await updateAgentConversation(projectRoot, id, { title });
    setRenaming(null);
  });

  return (
    // Pointer presses here are not the floating window's drag.
    <div className="ws-conv" ref={root} onPointerDown={(event) => event.stopPropagation()}>
      <button
        type="button"
        className="ws-conv__current"
        aria-haspopup="dialog"
        aria-expanded={open}
        title="Conversations in this project"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="ws-conv__label">{label}</span>
        <ChevronIcon direction="down" />
      </button>
      <button
        type="button"
        className="ws-icon-button"
        aria-label="New conversation"
        title="New conversation"
        disabled={agent.isSubmitting || !sessionId}
        onClick={() => {
          setOpen(false);
          agent.newConversation?.();
        }}
      >
        <ComposeIcon />
      </button>
      {open && (
        <div className="ws-conv__panel" role="dialog" aria-label="Conversations">
          <input
            type="search"
            className="ws-conv__search"
            aria-label="Search conversations"
            placeholder="Search conversations"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          {error && <p className="ws-conv__error" role="alert">{error}</p>}
          <ul className="ws-conv__list">
            {shown.length === 0 && <li className="ws-conv__empty">{query ? "No conversation matches." : "No conversations yet."}</li>}
            {shown.map((item) => (
              <li key={item.session_id} className="ws-conv__item" aria-current={item.session_id === sessionId ? "true" : undefined}>
                {renaming?.id === item.session_id ? (
                  <form
                    className="ws-conv__rename"
                    onSubmit={(event) => {
                      event.preventDefault();
                      void rename(item.session_id, renaming.title);
                    }}
                  >
                    <input
                      aria-label="Conversation title"
                      autoFocus
                      maxLength={120}
                      value={renaming.title}
                      onChange={(event) => setRenaming({ id: item.session_id, title: event.target.value })}
                      onKeyDown={(event) => event.key === "Escape" && setRenaming(null)}
                    />
                    <button type="submit">Save</button>
                  </form>
                ) : (
                  <button
                    type="button"
                    className="ws-conv__open"
                    disabled={agent.isSubmitting}
                    onClick={() => {
                      setOpen(false);
                      if (item.session_id !== sessionId) agent.openConversation?.(item.session_id);
                    }}
                  >
                    <span className="ws-conv__title">{item.title}</span>
                    <span className="ws-conv__meta">
                      {item.about} · {messageTime(item.last_active)}{item.archived ? " · archived" : ""}
                    </span>
                  </button>
                )}
                <button
                  type="button"
                  className="ws-icon-button ws-conv__more"
                  aria-label={`Actions for ${item.title}`}
                  aria-expanded={actionsFor === item.session_id}
                  onClick={() => {
                    setActionsFor(actionsFor === item.session_id ? null : item.session_id);
                    setDeleting(null);
                  }}
                >
                  <MoreIcon />
                </button>
                {actionsFor === item.session_id && deleting !== item.session_id && (
                  <div className="ws-conv__actions" role="group" aria-label={`Actions for ${item.title}`}>
                    <button type="button" onClick={() => { setRenaming({ id: item.session_id, title: item.titled ? item.title : "" }); setActionsFor(null); }}>Rename</button>
                    <button type="button" onClick={() => void act(async () => {
                      await updateAgentConversation(projectRoot, item.session_id, { archived: !item.archived });
                      setActionsFor(null);
                    })}>{item.archived ? "Restore" : "Archive"}</button>
                    <button type="button" className="ws-conv__danger" onClick={() => setDeleting(item.session_id)}>Delete…</button>
                  </div>
                )}
                {deleting === item.session_id && (
                  <div className="ws-conv__confirm" role="alertdialog" aria-label="Delete conversation">
                    <p>Delete “{item.title}”? Its messages are removed for good. Results, proposals and the analysis ledger stay.</p>
                    <button type="button" className="ws-conv__danger" onClick={() => void act(async () => {
                      await deleteAgentConversation(projectRoot, item.session_id);
                      setDeleting(null);
                      setActionsFor(null);
                      if (item.session_id === sessionId) agent.newConversation?.();
                    })}>Delete</button>
                    <button type="button" onClick={() => setDeleting(null)}>Cancel</button>
                  </div>
                )}
              </li>
            ))}
          </ul>
          <label className="ws-conv__archived">
            <input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} />
            Show archived
          </label>
        </div>
      )}
    </div>
  );
}
