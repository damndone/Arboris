import { useState, type CSSProperties } from "react";
import { useAgentSurfaceOptional } from "./AgentSurfaceContext";
import { AgentCapabilityPopover } from "./AgentCapabilityPopover";
import "./agent.css";

export function AgentComposer({ showScope = true }: { showScope?: boolean } = {}) {
  const agent = useAgentSurfaceOptional();
  if (!agent) return null;

  return <AgentComposerContent agent={agent} showScope={showScope} />;
}

function AgentComposerContent({
  agent,
  showScope,
}: {
  agent: NonNullable<ReturnType<typeof useAgentSurfaceOptional>>;
  showScope: boolean;
}) {
  const [contextOpen, setContextOpen] = useState(false);

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
  const contextLabel = `Context ${contextUsedTokens.toLocaleString()} / ${contextCapacityLabel} tokens`;
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

  return (
    <div data-testid="agent-composer" className="wb-agent-composer">
      <div className="wb-agent-composer-row">
        <textarea
          aria-label="Ask Agent"
          rows={1}
          value={prompt}
          placeholder="询问当前分析，或请求修改当前模型参数并重新运行"
          onChange={(event) => setPrompt(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              void sendPrompt(prompt);
            }
          }}
        />
        <div className="wb-agent-context-control">
          <button
            type="button"
            aria-label={contextLabel}
            aria-haspopup="dialog"
            aria-expanded={contextOpen}
            data-testid="agent-context-ring"
            title={contextLabel}
            className="wb-agent-ring"
            style={ringStyle}
            onClick={() => setContextOpen((open) => !open)}
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
        </div>
        <button
          type="button"
          aria-label="Send to Agent"
          className="wb-agent-send"
          disabled={isSubmitting || prompt.trim().length === 0}
          onClick={() => void sendPrompt(prompt)}
        >
          Send
        </button>
      </div>
      <div className="wb-agent-composer-meta">
        {showScope && (
          <>
            <span title={scopeLabel}>{scopeLabel}</span>
            <span aria-hidden="true">·</span>
          </>
        )}
        <label style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
          <span>Model</span>
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
        <span style={{ marginLeft: "auto" }} role="status" aria-live="polite">
          {isSubmitting ? "Thinking" : sessionStatus}
        </span>
        <AgentCapabilityPopover catalog={capabilityCatalog} />
      </div>
      {error && (
        <div role="alert" className="wb-agent-error">
          {error}
        </div>
      )}
    </div>
  );
}
