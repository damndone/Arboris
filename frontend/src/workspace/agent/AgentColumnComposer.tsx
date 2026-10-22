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
import { ContextUsageRing } from "../../workbench/agent/ContextUsageRing";
import { SendIcon, StopIcon } from "../icons";
import { AgentModeMenu, cycleMode } from "./AgentModeMenu";
import { AgentModelMenu } from "./AgentModelMenu";
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
  const textRef = useRef<HTMLTextAreaElement>(null);
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
    isSubmitting,
    model,
    modelOptions,
    scopeLabel,
    sendPrompt,
    sessionStatus,
    setModel,
    setPrompt,
  } = agent;
  const canSend = prompt.trim().length > 0;
  const busy = busyNow;
  // While a turn runs, a message waits for it (or steers it) instead of starting another.
  const canQueue = busy && Boolean(agent.queueTurnMessage) && !agent.queueMessageBusy;
  const submit = () => {
    if (!canSend) return;
    if (!busy) void sendPrompt(prompt);
    else if (canQueue) void agent.queueTurnMessage?.(steer ? "steer" : "follow_up", prompt);
  };
  const unfinished = !agent.isSubmitting ? agent.durableTurns ?? [] : [];

  return (
    <div className="ws-composer-wrap">
      {unfinished.map((turn) => (
        <div key={turn.turn_id} className="ws-composer__banner" role="status">
          <span>
            Previous turn unfinished{turn.requires_reconcile ? " · needs reconciliation" : ""}
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
      {busy && agent.queueTurnMessage && (
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
        <label htmlFor="ws-composer-text" className="ws-visually-hidden">
          Message the Agent
        </label>
        <textarea
          id="ws-composer-text"
          ref={textRef}
          aria-label="Ask Agent"
          rows={2}
          value={prompt}
          placeholder="Ask about this result, or tell Arboris what to do…"
          onChange={(event) => setPrompt(event.target.value)}
          onKeyDown={(event) => {
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
          <AgentCapabilityPopover
            catalog={capabilityCatalog}
            onPromptSelect={(next) => {
              setPrompt(next);
              textRef.current?.focus();
            }}
          />
          <AgentModeMenu agent={agent} disabled={busy} />
          <span className="ws-composer__spacer" />
          {busy && (
            <span className="ws-composer__status" role="status" aria-live="polite">
              {isSubmitting ? "Thinking…" : sessionStatus}
            </span>
          )}
          <ContextUsageRing
            used={contextUsedTokens}
            remaining={contextWindowTokens === null ? 0 : Math.max(0, contextWindowTokens - contextUsedTokens)}
            total={contextWindowTokens}
            size={18}
            strokeWidth={2}
            assumed={agent.contextWindowAssumed}
            compactAt={agent.compactAtTokens}
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
          {busy && canQueue && canSend && (
            <button type="submit" className="ws-composer__send" aria-label={steer ? "Steer the Agent" : "Queue for the Agent"} title={steer ? "Steer (Enter)" : "Queue (Enter)"}>
              <SendIcon />
            </button>
          )}
          {busy ? (
            <button type="button" className="ws-composer__send ws-composer__send--stop" aria-label="Stop Agent" title="Stop" onClick={() => void abortTurn()}>
              <StopIcon />
            </button>
          ) : (
            <button type="submit" className="ws-composer__send" aria-label="Send to Agent" title="Send (Enter)" disabled={!canSend}>
              <SendIcon />
            </button>
          )}
        </div>
      </form>
      {error && (
        <p role="alert" className="ws-composer__error">
          {error}
        </p>
      )}
      {agent.queueMessageNotice && <p className="ws-composer__note" role="status">{agent.queueMessageNotice}</p>}
    </div>
  );
}
