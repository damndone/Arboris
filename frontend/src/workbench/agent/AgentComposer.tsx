import { useRef, useState, type CSSProperties, type FocusEvent } from "react";
import { useAgentSurfaceOptional } from "./AgentSurfaceContext";
import { AgentCapabilityPopover } from "./AgentCapabilityPopover";
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
  const [contextOpen, setContextOpen] = useState(false);
  const promptInputRef = useRef<HTMLTextAreaElement>(null);

  const {
    contextPercent,
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
  const contextCapacityLabel = contextWindowTokens === null
    ? "unknown capacity"
    : contextWindowTokens.toLocaleString();
  const contextLabel = contextWindowTokens === null
    ? `Context estimate ${contextUsedTokens.toLocaleString()} tokens / capacity unavailable`
    : `Context estimate ${contextUsedTokens.toLocaleString()} used / ${contextCapacityLabel} total tokens`;
  const ringPercent = contextPercent ?? 0;
  const ringStyle = {
    "--agent-ring-progress": `${ringPercent}%`,
    aspectRatio: "1 / 1",
    width: "30px",
    height: "30px",
    minWidth: "30px",
    minHeight: "30px",
  } as CSSProperties;
  const remainingTokens = contextWindowTokens === null
    ? null
    : Math.max(0, contextWindowTokens - contextUsedTokens);
  const contextSummary = contextWindowTokens === null
    ? `~${contextUsedTokens.toLocaleString()} used · total unavailable`
    : `~${contextUsedTokens.toLocaleString()} used · ${remainingTokens!.toLocaleString()} remaining / ${contextWindowTokens.toLocaleString()} total`;

  const closeContextOnBlur = (event: FocusEvent<HTMLDivElement>) => {
    const next = event.relatedTarget;
    if (!(next instanceof Node) || !event.currentTarget.contains(next)) {
      setContextOpen(false);
    }
  };

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
          <div
            className="wb-agent-context-control"
            onMouseEnter={() => setContextOpen(true)}
            onMouseLeave={() => setContextOpen(false)}
            onFocusCapture={() => setContextOpen(true)}
            onBlurCapture={closeContextOnBlur}
          >
            <button
              type="button"
              aria-label={contextLabel}
              aria-haspopup="dialog"
              aria-expanded={contextOpen}
              aria-valuemin={contextWindowTokens === null ? undefined : 0}
              aria-valuemax={contextWindowTokens ?? undefined}
              aria-valuenow={contextWindowTokens === null ? undefined : Math.min(contextWindowTokens, contextUsedTokens)}
              data-testid="agent-context-ring"
              title={contextLabel}
              className="wb-agent-ring"
              style={ringStyle}
              onClick={() => setContextOpen(true)}
            >
              <span aria-hidden="true">
                {contextPercent === null ? "?" : `${Math.round(contextPercent)}%`}
              </span>
            </button>
            {contextOpen && (
              <div
                role="dialog"
                aria-label="Agent context details"
                data-testid="agent-context-popover"
                className="wb-agent-context-popover"
              >
                <strong>Context window</strong>
                <div>{contextUsedTokens.toLocaleString()} tokens used</div>
                <div>{contextWindowTokens === null ? "Capacity unavailable" : `${contextWindowTokens.toLocaleString()} tokens capacity`}</div>
                <div>{remainingTokens === null ? "Remaining: unknown" : `Remaining: ${remainingTokens.toLocaleString()} tokens`}</div>
                <div className="wb-agent-context-popover-model">Model: {model}</div>
              </div>
            )}
            <span
              data-testid="agent-context-summary"
              className="wb-agent-context-summary"
              title={contextLabel}
            >
              {contextSummary}
            </span>
          </div>
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
          <span className="wb-agent-session-status" role="status" aria-live="polite">
            {isSubmitting ? "Thinking" : sessionStatus}
          </span>
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
