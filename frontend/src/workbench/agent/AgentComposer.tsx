import { useRef } from "react";
import { useAgentSurfaceOptional } from "./AgentSurfaceContext";
import { AgentCapabilityPopover } from "./AgentCapabilityPopover";
import { ContextUsageRing } from "./ContextUsageRing";
import "./agent.css";

export function AgentComposer({
  showScope = true,
  variant = "graph",
}: {
  showScope?: boolean;
  variant?: "graph" | "terminal";
} = {}) {
  const agent = useAgentSurfaceOptional();
  if (!agent) return null;

  return <AgentComposerContent agent={agent} showScope={showScope} variant={variant} />;
}

function AgentComposerContent({
  agent,
  showScope,
  variant,
}: {
  agent: NonNullable<ReturnType<typeof useAgentSurfaceOptional>>;
  showScope: boolean;
  variant: "graph" | "terminal";
}) {
  const promptInputRef = useRef<HTMLTextAreaElement>(null);

  const {
    contextUsedTokens,
    contextWindowTokens,
    error,
    isSubmitting,
    model,
    modelOptions,
    capabilityCatalog,
    prompt,
    scopeLabel,
    sendPrompt,
    sessionStatus,
    setModel,
    setPrompt,
  } = agent;
  const remainingTokens = contextWindowTokens === null
    ? 0
    : Math.max(0, contextWindowTokens - contextUsedTokens);

  return (
    <div
      data-testid="agent-composer"
      className={`wb-agent-composer${variant === "terminal" ? " wb-agent-terminal-composer" : ""}`}
    >
      <div className="wb-agent-composer-input-row">
        {variant === "terminal" && (
          <span
            data-testid="agent-terminal-prompt-marker"
            className="wb-agent-terminal-input-marker"
            aria-hidden="true"
          >
            ❯
          </span>
        )}
        <textarea
          ref={promptInputRef}
          aria-label="Ask Agent"
          rows={1}
          value={prompt}
          placeholder="Ask about the current analysis or request a typed change and rerun"
          onChange={(event) => setPrompt(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void sendPrompt(prompt);
            }
          }}
        />
      </div>
      <div className="wb-agent-composer-actions">
        <div className="wb-agent-composer-actions-left">
          <button
            type="button"
            className="wb-agent-add-context"
            data-testid="agent-add-context"
            aria-label="Add context"
            title="Focus the Agent prompt"
            onClick={() => promptInputRef.current?.focus()}
          >
            <span aria-hidden="true">＋</span>
          </button>
          <AgentCapabilityPopover
            catalog={capabilityCatalog}
            onPromptSelect={(nextPrompt) => {
              setPrompt(nextPrompt);
              promptInputRef.current?.focus();
            }}
          />
          {showScope && <span className="wb-agent-composer-scope" title={scopeLabel}>{scopeLabel}</span>}
        </div>
        <div className="wb-agent-composer-actions-right">
          <ContextUsageRing
            used={contextUsedTokens}
            remaining={remainingTokens}
            total={contextWindowTokens}
            size={20}
            strokeWidth={2}
          />
          <label className="wb-agent-model-control">
            <span className="wb-agent-visually-hidden">Model</span>
            <select
              role="listbox"
              aria-label="Agent model"
              value={model}
              disabled={isSubmitting || modelOptions.length === 0}
              onChange={(event) => void setModel(event.target.value)}
            >
              {modelOptions.length === 0 && <option value={model}>{model}</option>}
              {modelOptions.map((option) => (
                <option
                  key={option.request_model}
                  value={option.request_model}
                  title={option.request_model}
                >
                  {option.display_name}
                </option>
              ))}
            </select>
          </label>
          {(isSubmitting || sessionStatus.toLowerCase() !== "idle") && (
            <span className="wb-agent-session-status" role="status" aria-live="polite">
              {isSubmitting ? "Thinking" : sessionStatus}
            </span>
          )}
          <button
            type="button"
            className="wb-agent-voice"
            aria-label="Voice input"
            title="Voice input is not configured"
            disabled
          >
            <span aria-hidden="true">⌁</span>
          </button>
          <button
            type="button"
            aria-label="Send to Agent"
            className="wb-agent-send"
            disabled={isSubmitting || prompt.trim().length === 0}
            onClick={() => void sendPrompt(prompt)}
          >
            <span aria-hidden="true">↑</span>
          </button>
        </div>
      </div>
      {error && (
        <div role="alert" className="wb-agent-error">
          {error}
        </div>
      )}
    </div>
  );
}
