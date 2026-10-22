// v1.9.1 — the model picker: which model, how hard it thinks, how much it reads.
// Thinking offers the efforts the model accepts (detected from the provider's
// model list, else by its id); the context limit offers Full and the usual caps
// below the model's window. Both are saved on the provider's model record, so
// they hold for every conversation with that model.

import type { AgentModelOption, AgentModelSettings } from "../../workbench/agent/agentTypes";
import { ComposerMenu, Segmented } from "./ComposerMenu";

type Effort = NonNullable<AgentModelOption["reasoning_effort"]>;
const EFFORT_NAME: Record<Effort, string> = {
  none: "Off", minimal: "Minimal", low: "Low", medium: "Medium", high: "High", xhigh: "X-High", max: "Max",
};

/** The effort a model runs at when none is chosen: the documented high, else its strongest. */
export function defaultEffort(efforts: readonly Effort[]): Effort | null {
  if (efforts.length === 0) return null;
  return efforts.includes("high") ? "high" : efforts[efforts.length - 1];
}

const ONE_MILLION = 1_000_000;
const LIMITS = [256_000, 128_000, 64_000];

function tokens(value: number): string {
  return value >= ONE_MILLION ? `${+(value / ONE_MILLION).toFixed(1)}M` : `${Math.round(value / 1000)}K`;
}

/** The model's own window, as configured or detected. */
export function modelWindow(model: AgentModelOption): number | null {
  return model.context_window_tokens ?? (model.supports_1m ? ONE_MILLION : null);
}

/** Full (the model's window) and the usual caps below it. */
export function limitOptions(model: AgentModelOption): { value: string; label: string }[] {
  const window = modelWindow(model);
  if (window === null) return [];
  return [{ value: "full", label: `Full ${tokens(window)}` },
    ...LIMITS.filter((limit) => limit < window).map((limit) => ({ value: String(limit), label: tokens(limit) }))];
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
  const efforts = current?.reasoning_efforts ?? [];
  const effort = current?.reasoning_effort ?? defaultEffort(efforts);
  const limits = current ? limitOptions(current) : [];
  const name = current?.display_name ?? model;
  const label = (
    <span className="ws-menu__label">
      <span className="ws-menu__label-main">{name}</span>
      {effort && <span className="ws-menu__label-sub">{effort === "none" ? "Thinking off" : EFFORT_NAME[effort]}</span>}
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
          {current && onSettings && (efforts.length > 0 || limits.length > 1) && (
            <div className="ws-menu__section ws-menu__section--settings">
              {efforts.length > 0 && effort && (
                <Segmented
                  label="Thinking"
                  options={efforts.map((value) => ({ value, label: EFFORT_NAME[value] }))}
                  value={effort}
                  onChange={(value) => onSettings(current.request_model, { reasoning_effort: value })}
                />
              )}
              {limits.length > 1 && (
                <Segmented
                  label="Context limit"
                  options={limits}
                  value={current.context_limit_tokens ? String(current.context_limit_tokens) : "full"}
                  onChange={(value) => onSettings(current.request_model, {
                    context_limit_tokens: value === "full" ? null : Number(value),
                  })}
                />
              )}
              <p className="ws-menu__hint">
                Saved for this model. A lower limit compacts the conversation sooner: faster and cheaper, less remembered.
              </p>
            </div>
          )}
        </>
      )}
    </ComposerMenu>
  );
}
