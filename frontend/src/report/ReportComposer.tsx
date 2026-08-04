import { useEffect, useRef, useState } from "react";
import { useAgentSurfaceOptional } from "../workbench/agent/AgentSurfaceContext";
import { ContextUsageRing } from "../workbench/agent/ContextUsageRing";
import "../workbench/agent/agent.css";
import "./report.css";

export interface ReportComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  submitLabel: string;
  placeholder: string;
  contextLines: readonly string[];
  contextDetails?: readonly string[];
  contextUsedTokens: number;
  contextWindowTokens?: number | null;
  allowEmptySubmit?: boolean;
  busy?: boolean;
  disabled?: boolean;
  ariaLabel?: string;
  modelLabel?: string;
  contextButtonLabel?: string;
  focusRequest?: number;
}

/**
 * Report-specific input surface. It intentionally shares the Agent visual
 * language and model catalogue, but its submit action is supplied by ReportView
 * and can only create/revise prose. It never calls Agent send/confirm actions.
 */
export function ReportComposer({
  value,
  onChange,
  onSubmit,
  submitLabel,
  placeholder,
  contextLines,
  contextDetails = [],
  contextUsedTokens,
  contextWindowTokens,
  allowEmptySubmit = false,
  busy = false,
  disabled = false,
  ariaLabel = "Report instruction",
  modelLabel = "Report model",
  contextButtonLabel = "View report context",
  focusRequest = 0,
}: ReportComposerProps) {
  const agent = useAgentSurfaceOptional();
  const [contextOpen, setContextOpen] = useState(false);
  const [modelSwitching, setModelSwitching] = useState(false);
  const composerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const modelOptions = agent?.modelOptions ?? [];
  const model = agent?.model ?? "Default model";
  const selectedModel = modelOptions.find((option) => option.request_model === model);
  const total = contextWindowTokens
    ?? selectedModel?.context_window_tokens
    ?? agent?.contextWindowTokens
    ?? null;
  const remaining = total === null ? 0 : Math.max(0, total - contextUsedTokens);
  const canSubmit = !busy
    && !disabled
    && !modelSwitching
    && (allowEmptySubmit || value.trim().length > 0);

  useEffect(() => {
    if (focusRequest <= 0 || disabled) return;
    textareaRef.current?.focus();
    textareaRef.current?.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [disabled, focusRequest]);

  useEffect(() => {
    if (!contextOpen) return undefined;
    const closeOnOutsidePress = (event: MouseEvent) => {
      const target = event.target;
      if (target instanceof Node && composerRef.current?.contains(target)) return;
      setContextOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setContextOpen(false);
    };
    document.addEventListener("mousedown", closeOnOutsidePress);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsidePress);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [contextOpen]);

  return (
    <div
      data-testid="report-composer"
      className={`wb-agent-composer report-composer${busy ? " report-composer--busy" : ""}`}
      ref={composerRef}
    >
      <div className="wb-agent-composer-input-row report-composer__input-row">
        <textarea
          ref={textareaRef}
          aria-label={ariaLabel}
          rows={2}
          value={value}
          placeholder={placeholder}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              if (canSubmit) onSubmit();
            }
          }}
        />
      </div>
      <div className="wb-agent-composer-actions report-composer__actions">
        <div className="wb-agent-composer-actions-left">
          <button
            type="button"
            className="wb-agent-add-context report-composer__context-button"
            aria-label={contextButtonLabel}
            aria-expanded={contextOpen}
            title="Show the read-only evidence sent to the report writer"
            onClick={() => setContextOpen((open) => !open)}
          >
            <span aria-hidden="true">＋</span>
            <span className="report-composer__context-label">Context</span>
          </button>
          <span className="wb-agent-composer-scope report-composer__scope">
            Report writer · source evidence is read-only
          </span>
        </div>
        <div className="wb-agent-composer-actions-right">
          <ContextUsageRing
            used={contextUsedTokens}
            remaining={remaining}
            total={total}
            size={20}
            strokeWidth={2}
          />
          <label className="wb-agent-model-control">
            <span className="wb-agent-visually-hidden">{modelLabel}</span>
            <select
              role="listbox"
              aria-label={modelLabel}
              value={model}
              disabled={busy || disabled || modelSwitching || modelOptions.length === 0 || !agent}
              onChange={(event) => {
                if (agent) {
                  setModelSwitching(true);
                  void agent.setModel(event.target.value).finally(() => setModelSwitching(false));
                }
              }}
            >
              {modelOptions.length === 0 && <option value={model}>{model}</option>}
              {modelOptions.map((option) => (
                <option key={option.request_model} value={option.request_model} title={option.request_model}>
                  {option.display_name}
                </option>
              ))}
            </select>
          </label>
          {(busy || modelSwitching) && (
            <span className="wb-agent-session-status" role="status" aria-live="polite">
              {modelSwitching ? "Switching model" : "Drafting"}
            </span>
          )}
          <button
            type="button"
            className="wb-agent-send report-composer__submit"
            aria-label={submitLabel}
            title={submitLabel}
            disabled={!canSubmit}
            onClick={onSubmit}
          >
            <span aria-hidden="true">↑</span>
          </button>
        </div>
      </div>
      {contextOpen && (
        <div
          className="wb-agent-context-popover report-composer__context-popover"
          data-testid="report-context-popover"
          role="status"
        >
          <strong>Report context</strong>
          {contextLines.length > 0 ? contextLines.map((line) => <div key={line}>{line}</div>) : (
            <div>No report evidence is available yet.</div>
          )}
          {contextDetails.length > 0 && (
            <div className="report-composer__context-details">
              <strong>Evidence preview</strong>
              {contextDetails.map((detail) => <div key={detail}>{detail}</div>)}
            </div>
          )}
          <div className="report-composer__readonly-note">Source facts are read-only.</div>
        </div>
      )}
    </div>
  );
}
