// v1.9.1 — the model picker: which model, how hard it thinks, how much it reads.
// Thinking and context are saved on the provider's model record, so they hold
// for every conversation with that model. A model that does not take a
// thinking effort, or does not support 1M tokens, shows no such control.

import type { AgentModelOption, AgentModelSettings } from "../../workbench/agent/agentTypes";
import { ComposerMenu, Segmented } from "./ComposerMenu";

type Effort = "none" | "low" | "high" | "max";
const EFFORTS: { value: Effort; label: string }[] = [
  { value: "none", label: "Off" },
  { value: "low", label: "Low" },
  { value: "high", label: "High" },
  { value: "max", label: "Max" },
];
const EFFORT_LABEL: Record<Effort, string> = { none: "Thinking off", low: "Low", high: "High", max: "Max" };
/** The documented default when a model with thinking has no stored choice. */
const DEFAULT_EFFORT: Effort = "high";

const STANDARD_CONTEXT = 128_000;
const ONE_MILLION = 1_000_000;

export function contextChoice(model: AgentModelOption): "standard" | "1m" {
  return (model.context_window_tokens ?? STANDARD_CONTEXT) >= ONE_MILLION ? "1m" : "standard";
}

export function AgentModelMenu({
  model,
  options,
  disabled,
  onSelect,
  onSettings,
}: {
  model: string;
  options: AgentModelOption[];
  disabled?: boolean;
  onSelect: (requestModel: string) => void;
  onSettings?: (requestModel: string, patch: AgentModelSettings) => void;
}) {
  const current = options.find((option) => option.request_model === model);
  const effort = (current?.reasoning_effort ?? DEFAULT_EFFORT) as Effort;
  const name = current?.display_name ?? model;
  const label = (
    <span className="ws-menu__label">
      <span className="ws-menu__label-main">{name}</span>
      {current?.supports_reasoning_effort && <span className="ws-menu__label-sub">{EFFORT_LABEL[effort]}</span>}
    </span>
  );
  return (
    <ComposerMenu label={label} title={`Model: ${name}`} disabled={disabled || options.length === 0} className="ws-model-menu">
      {() => (
        <>
          <div className="ws-menu__section" role="radiogroup" aria-label="Model">
            {options.map((option) => (
              <button
                key={option.request_model}
                type="button"
                role="radio"
                aria-checked={option.request_model === model}
                className="ws-menu__item"
                title={option.request_model}
                onClick={() => onSelect(option.request_model)}
              >
                <span className="ws-menu__check" aria-hidden="true">{option.request_model === model ? "✓" : ""}</span>
                <span className="ws-menu__item-name">{option.display_name}</span>
              </button>
            ))}
          </div>
          {current && onSettings && (current.supports_reasoning_effort || current.supports_1m) && (
            <div className="ws-menu__section ws-menu__section--settings">
              {current.supports_reasoning_effort && (
                <Segmented
                  label="Thinking"
                  options={EFFORTS}
                  value={effort}
                  onChange={(value) => onSettings(current.request_model, { reasoning_effort: value })}
                />
              )}
              {current.supports_1m && (
                <Segmented
                  label="Context"
                  options={[{ value: "standard", label: "128K" }, { value: "1m", label: "1M" }]}
                  value={contextChoice(current)}
                  onChange={(value) => onSettings(current.request_model, {
                    context_window_tokens: value === "1m" ? ONE_MILLION : STANDARD_CONTEXT,
                  })}
                />
              )}
              <p className="ws-menu__hint">Saved for this model. More thinking and context answer better and take longer.</p>
            </div>
          )}
        </>
      )}
    </ComposerMenu>
  );
}
