// v1.9.0 — the Agent column's composer (design spec §8.3 #9). What the Agent
// is about sits above the text; the text grows with what is typed; one row
// below holds capabilities, context use, the model and send. Controls that do
// nothing yet (attach context, voice) are left out rather than shown dead.

import { useLayoutEffect, useRef } from "react";
import { useAgentSurfaceOptional } from "../../workbench/agent/AgentSurfaceContext";
import { AgentCapabilityPopover } from "../../workbench/agent/AgentCapabilityPopover";
import { ContextUsageRing } from "../../workbench/agent/ContextUsageRing";
import { SendIcon, StopIcon } from "../icons";
import "./agentColumnComposer.css";

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
  const busy = isSubmitting || sessionStatus.toLowerCase() === "running";

  return (
    <div className="ws-composer-wrap">
      <form
        className="ws-composer"
        data-testid="agent-composer"
        onSubmit={(event) => {
          event.preventDefault();
          if (canSend && !isSubmitting) void sendPrompt(prompt);
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
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              if (canSend && !isSubmitting) void sendPrompt(prompt);
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
          />
          <label className="ws-composer__model">
            <span className="ws-visually-hidden">Model</span>
            <select
              aria-label="Agent model"
              value={model}
              disabled={isSubmitting || modelOptions.length === 0}
              onChange={(event) => void setModel(event.target.value)}
            >
              {modelOptions.length === 0 && <option value={model}>{model}</option>}
              {modelOptions.map((option) => (
                <option key={option.request_model} value={option.request_model} title={option.request_model}>
                  {option.display_name}
                </option>
              ))}
            </select>
          </label>
          {isSubmitting ? (
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
      <p className="ws-composer__note">Read-only analyses run at once · changes wait for your OK · Shift+Enter for a new line</p>
    </div>
  );
}
