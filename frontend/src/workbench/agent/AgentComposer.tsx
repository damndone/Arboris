import { useEffect, useRef, useState } from "react";
import { useAgentSurfaceOptional } from "./AgentSurfaceContext";
import { AgentCapabilityPopover } from "./AgentCapabilityPopover";
import { ContextUsageRing } from "./ContextUsageRing";
import "./agent.css";

export function AgentComposer({
  showScope = true,
  variant = "graph",
  onExpand,
}: {
  showScope?: boolean;
  variant?: "graph" | "terminal" | "compact";
  onExpand?: () => void;
} = {}) {
  const agent = useAgentSurfaceOptional();
  if (!agent) return null;

  if (variant === "compact") {
    return <CompactAgentComposer agent={agent} onExpand={onExpand} />;
  }

  return <AgentComposerContent agent={agent} showScope={showScope} variant={variant} />;
}

function CompactAgentComposer({
  agent,
  onExpand,
}: {
  agent: NonNullable<ReturnType<typeof useAgentSurfaceOptional>>;
  onExpand?: () => void;
}) {
  const promptInputRef = useRef<HTMLTextAreaElement>(null);
  const observedActiveTurn = useRef(false);
  const [compactTurn, setCompactTurn] = useState<{
    startedAt: number;
    completedAt?: number;
    stopped?: boolean;
  } | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const remainingTokens = agent.contextWindowTokens === null
    ? 0
    : Math.max(0, agent.contextWindowTokens - agent.contextUsedTokens);
  const isActive = agent.isSubmitting || ["running", "working"].includes(agent.sessionStatus.toLowerCase());
  const activityStartAt = agent.activeTurnStartedAt ?? compactTurn?.startedAt ?? null;
  const activityEndAt = isActive ? now : compactTurn?.completedAt ?? now;
  const elapsedSeconds = activityStartAt === null
    ? 0
    : Math.max(0, Math.floor((activityEndAt - activityStartAt) / 1_000));
  const hasActivity = isActive || compactTurn?.completedAt !== undefined;

  useEffect(() => {
    if (!isActive || activityStartAt === null) return;
    setNow(Date.now());
    const interval = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(interval);
  }, [activityStartAt, isActive]);

  useEffect(() => {
    if (isActive) {
      if (compactTurn) observedActiveTurn.current = true;
      return;
    }
    if (compactTurn && observedActiveTurn.current && compactTurn.completedAt === undefined) {
      setCompactTurn((current) => current && {
        ...current,
        completedAt: Date.now(),
      });
      observedActiveTurn.current = false;
    }
  }, [compactTurn, isActive]);

  const submitCompactPrompt = () => {
    if (agent.prompt.trim().length === 0 || isActive) return;
    observedActiveTurn.current = false;
    setCompactTurn({ startedAt: Date.now() });
    void agent.sendPrompt(agent.prompt);
  };

  const activityText = isActive
    ? `Working · ${elapsedSeconds}s · ${compactActivityLabel(agent.lastEventType)}`
    : `${compactTurn?.stopped || agent.error ? "Stopped" : "Processed"} · ${elapsedSeconds}s`;

  return (
    <div className="wb-agent-compact-composer-shell">
      {hasActivity && (
        <button
          type="button"
          className="wb-agent-compact-activity"
          aria-label="View Agent activity"
          onClick={onExpand}
        >
          <span>{activityText}</span>
          <span aria-hidden="true">›</span>
        </button>
      )}
      <div className="wb-agent-compact-composer-row">
        <div
          data-testid="agent-compact-composer"
          className="wb-agent-compact-composer"
        >
          <button
            type="button"
            className="wb-agent-add-context"
            aria-label="Focus Agent prompt"
            title="Focus the Agent prompt"
            onClick={() => promptInputRef.current?.focus()}
          >
            <span aria-hidden="true">＋</span>
          </button>
          <textarea
            ref={promptInputRef}
            aria-label="Ask Agent"
            rows={1}
            value={agent.prompt}
            placeholder="Ask about the current analysis"
            onChange={(event) => agent.setPrompt(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submitCompactPrompt();
              }
            }}
          />
          <div className="wb-agent-compact-composer__actions">
        <ContextUsageRing
          used={agent.contextUsedTokens}
          remaining={remainingTokens}
          total={agent.contextWindowTokens}
          size={18}
          strokeWidth={2}
        />
        <label className="wb-agent-model-control wb-agent-compact-composer__model-control">
          <span className="wb-agent-visually-hidden">Model</span>
          <select
            role="listbox"
            aria-label="Agent model"
            value={agent.model}
            disabled={isActive || agent.modelOptions.length === 0}
            onChange={(event) => void agent.setModel(event.target.value)}
          >
            {agent.modelOptions.length === 0 && <option value={agent.model}>{agent.model}</option>}
            {agent.modelOptions.map((option) => (
              <option key={option.request_model} value={option.request_model}>
                {option.display_name}
              </option>
            ))}
          </select>
        </label>
            {isActive ? (
              <button
                type="button"
                aria-label="Stop Agent"
                title="Stop the current Agent request"
                className="wb-agent-stop"
                onClick={() => {
                  setCompactTurn((current) => current && { ...current, stopped: true });
                  void agent.abortTurn();
                }}
              >
                <span aria-hidden="true">■</span>
              </button>
            ) : (
              <button
                type="button"
                aria-label="Send to Agent"
                className="wb-agent-send"
                disabled={agent.prompt.trim().length === 0}
                onClick={submitCompactPrompt}
              >
                <span aria-hidden="true">↑</span>
              </button>
            )}
          </div>
        </div>
        <button
          type="button"
          className="wb-agent-compact-composer__expand"
          aria-label="Expand Agent panel"
          title="Expand Agent panel"
          onClick={onExpand}
        >
          <span aria-hidden="true">▲</span>
        </button>
      </div>
    </div>
  );
}

function compactActivityLabel(lastEventType: string | null): string {
  const eventType = lastEventType?.toLowerCase() ?? "";
  if (eventType.includes("tool")) return "Checking evidence";
  if (eventType.includes("proposal")) return "Preparing proposal";
  if (eventType.includes("response") || eventType.includes("message")) return "Drafting answer";
  return "Working";
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
    abortTurn,
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
          {isSubmitting ? (
            <button
              type="button"
              aria-label="Stop Agent"
              title="Stop the current Agent request"
              className="wb-agent-stop"
              onClick={() => void abortTurn()}
            >
              <span aria-hidden="true">■</span>
            </button>
          ) : (
            <button
              type="button"
              aria-label="Send to Agent"
              className="wb-agent-send"
              disabled={prompt.trim().length === 0}
              onClick={() => void sendPrompt(prompt)}
            >
              <span aria-hidden="true">↑</span>
            </button>
          )}
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
