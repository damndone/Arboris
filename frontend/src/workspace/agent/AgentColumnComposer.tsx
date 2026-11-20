import { agentTurnActive } from "../../workbench/agent/AgentRunControls";
// v1.9.0 — the Agent column's composer (design spec §8.3 #9). What the Agent
// is about sits above the text; the text grows with what is typed; one row
// below holds capabilities, the mode, context use, the model and send.
// v1.9.1: one mode control replaces the Mode select and the Review-first
// toggle; while a turn runs a message is queued (or steers, when chosen);
// an unfinished turn is one banner. Controls that do nothing yet (attach
// context, voice) are left out rather than shown dead.

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useAgentSurfaceOptional } from "../../workbench/agent/AgentSurfaceContext";
import { AgentCapabilityPopover } from "../../workbench/agent/AgentCapabilityPopover";
import type { AgentMessage } from "../../workbench/agent/agentTypes";
import { ContextUsageRing } from "../../workbench/agent/ContextUsageRing";
import { SendIcon, StopIcon } from "../icons";
import { AgentModeMenu, cycleMode } from "./AgentModeMenu";
import { AgentModelMenu } from "./AgentModelMenu";
import { useAgentSlashCommands } from "../../workbench/agent/useAgentSlashCommands";
import "./agentColumnComposer.css";
import "./composerMenu.css";

const MAX_TEXT_HEIGHT = 200;

/** The focus label in reader terms: the whole project, or the step in view. */
export function focusChipText(label: string): string {
  if (label.startsWith("Global Agent")) return "Whole project";
  return label.replace(/^Current chain · /, "").replace(/^Project · /, "Project · ");
}

export function AgentColumnComposer() {
  const agent = useAgentSurfaceOptional();
  const { handleCommand, feedback } = useAgentSlashCommands(agent);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [attached, setAttached] = useState<NonNullable<AgentMessage["attachments"]>>([]);
  const [attachError, setAttachError] = useState<string | null>(null);
  const [dropping, setDropping] = useState(false);
  const prompt = agent?.prompt ?? "";
  const [steer, setSteer] = useState(false);
  const busyNow = agent ? agentTurnActive(agent) : false;
  useEffect(() => { setSteer(false); }, [agent?.sessionId, busyNow]);

  useLayoutEffect(() => {
    const text = textRef.current;
    if (!text) return;
    text.style.height = "auto";
    text.style.height = `${Math.min(MAX_TEXT_HEIGHT, text.scrollHeight)}px`;
  }, [prompt]);

  if (!agent) return null;
  const {
    abortTurn,
    capabilityCatalog,
    contextUsedTokens,
    contextWindowTokens,
    error,
    model,
    modelOptions,
    scopeLabel,
    sendPrompt,
    setModel,
    setPrompt,
  } = agent;
  const canSend = prompt.trim().length > 0;
  const commandDraft = prompt.trim().startsWith("/");
  const busy = busyNow;
  // While a turn runs, a message waits for it (or steers it) instead of starting another.
  const canQueue = busy && Boolean(agent.queueTurnMessage) && !agent.queueMessageBusy;
  const submit = () => {
    if (!canSend) return;
    if (handleCommand(prompt)) return;
    if (!busy) {
      void sendPrompt(prompt, attached);
      setAttached([]);
      setAttachError(null);
    }
    else if (canQueue) void agent.queueTurnMessage?.(steer ? "steer" : "follow_up", prompt);
  };
  const imageUnread = attached.some((item) => item.kind === "image")
    && agent.modelOptions?.find((option) => option.request_model === agent.model)?.supports_vision === false;
  const attach = async (files: Iterable<File>) => {
    if (!agent.attachFile) return;
    setAttachError(null);
    for (const file of files) {
      try {
        const record = await agent.attachFile(file);
        setAttached((current) => current.some((item) => item.attachment_id === record.attachment_id) ? current : [...current, record].slice(0, 8));
      } catch (problem) {
        setAttachError(problem instanceof Error ? problem.message : `Could not attach ${file.name}`);
      }
    }
  };
  const unfinished = !busyNow ? agent.durableTurns ?? [] : [];

  return (
    <div className="ws-composer-wrap">
      {unfinished.map((turn) => (
        <div key={turn.turn_id} className="ws-composer__banner" role="status">
          <span>
            Turn unfinished{turn.requires_reconcile ? " · needs reconciliation" : ""}
          </span>
          <button
            type="button"
            title="Resuming starts a model request. The server checks the original turn is no longer running first."
            onClick={() => void agent.resumeTurn?.(turn.turn_id)}
          >
            Resume
          </button>
        </div>
      ))}
      {busy && agent.queueTurnMessage && !commandDraft && (
        <div className="ws-composer__queue">
          <span>{steer ? "Your message steers the current turn" : "Your message waits for this turn to finish"}</span>
          <button type="button" aria-pressed={steer} onClick={() => setSteer((value) => !value)}>
            Steer
          </button>
        </div>
      )}
      <form
        className="ws-composer"
        data-testid="agent-composer"
        data-dropping={dropping || undefined}
        onDragOver={(event) => {
          if (!event.dataTransfer.types.includes("Files")) return;
          event.preventDefault();
          setDropping(true);
        }}
        onDragLeave={() => setDropping(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDropping(false);
          void attach(Array.from(event.dataTransfer.files));
        }}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <div className="ws-composer__focus">
          <span className="ws-composer__chip" title={scopeLabel}>
            <span className="ws-composer__dot" aria-hidden="true" />
            <span className="ws-visually-hidden">About: </span>
            {focusChipText(scopeLabel)}
          </span>
        </div>
        {attached.length > 0 && (
          <div className="ws-composer__attachments" data-testid="agent-composer-attachments">
            {attached.map((item) => (
              <span key={item.attachment_id} className="ws-composer__attachment" title={`Sent to the model with your message: ${item.name}`}>
                {item.kind === "image" && agent.attachmentUrl
                  ? <img src={agent.attachmentUrl(item.attachment_id)} alt="" />
                  : null}
                <span>{item.name}</span>
                <button type="button" aria-label={`Remove ${item.name}`} onClick={() => setAttached((current) => current.filter((other) => other !== item))}>×</button>
              </span>
            ))}
          </div>
        )}
        {attachError && <div className="ws-composer__attach-error" role="alert">{attachError}</div>}
        {imageUnread && <div className="ws-composer__attach-error">{agent.model} can't read images. Switch to a vision model to use them.</div>}
        <label htmlFor="ws-composer-text" className="ws-visually-hidden">
          Message the Agent
        </label>
        <textarea
          id="ws-composer-text"
          ref={textRef}
          aria-label="Ask Agent"
          rows={2}
          value={prompt}
          placeholder="Ask Arboris…"
          onChange={(event) => setPrompt(event.target.value)}
          onPaste={(event) => {
            const files = Array.from(event.clipboardData.files);
            if (files.length === 0) return;
            event.preventDefault();
            void attach(files);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape" && busy && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void abortTurn();
              return;
            }
            if (event.key === "Tab" && event.shiftKey && !busy) {
              event.preventDefault();
              cycleMode(agent);
              return;
            }
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }}
        />
        <div className="ws-composer__bar">
          <input
            ref={fileRef}
            type="file"
            multiple
            hidden
            data-testid="agent-attach-input"
            onChange={(event) => {
              void attach(Array.from(event.target.files ?? []));
              event.target.value = "";
            }}
          />
          <button type="button" className="ws-composer__attach" aria-label="Attach files" title="Attach files or images" disabled={busy || !agent.attachFile} onClick={() => fileRef.current?.click()}>+</button>
          <AgentCapabilityPopover
            catalog={capabilityCatalog}
            onPromptSelect={(next) => {
              setPrompt(next);
              textRef.current?.focus();
            }}
          />
          <AgentModeMenu agent={agent} disabled={busy} />
          <span className="ws-composer__spacer" />
          <ContextUsageRing
            used={contextUsedTokens}
            remaining={contextWindowTokens === null ? 0 : Math.max(0, contextWindowTokens - contextUsedTokens)}
            total={contextWindowTokens}
            size={20}
            strokeWidth={3}
            assumed={agent.contextWindowAssumed}
            compactAt={agent.compactAtTokens}
            breakdown={agent.contextBreakdown}
            onCompact={agent.compactConversation && agent.messages.some((message) => message.role === "user") ? () => void agent.compactConversation?.() : undefined}
            compacting={agent.compacting}
          />
          <AgentModelMenu
            model={model}
            options={modelOptions}
            disabled={busy}
            onSelect={(value) => void setModel(value)}
            onSettings={agent.setModelSettings ? (value, patch) => void agent.setModelSettings?.(value, patch) : undefined}
          />
          {busy && canSend && (canQueue || commandDraft) && (
            <button type="submit" className="ws-composer__send"
              aria-label={commandDraft ? "Run Agent command" : steer ? "Steer the Agent" : "Queue for the Agent"}
              title={commandDraft ? "Run command (Enter)" : steer ? "Steer (Enter)" : "Queue (Enter)"}>
              <SendIcon />
            </button>
          )}
          {busy ? (
            <button type="button" className="ws-composer__send ws-composer__send--stop" aria-label="Stop Agent" title="Stop (Esc)" onClick={() => void abortTurn()}>
              <StopIcon />
            </button>
          ) : (
            <button type="submit" className="ws-composer__send" aria-label="Send to Agent" title="Send (Enter)" disabled={!canSend}>
              <SendIcon />
            </button>
          )}
        </div>
      </form>
      {feedback && <p role={feedback.error ? "alert" : "status"} className="ws-composer__note">{feedback.text}</p>}
      {error && (
        <p role="alert" className="ws-composer__error">
          {error}
        </p>
      )}
      {agent.queueMessageNotice && <p className="ws-composer__note" role="status">{agent.queueMessageNotice}</p>}
    </div>
  );
}
