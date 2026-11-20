// v1.9.1 — the model picker: which model, how hard it thinks, how much it reads.
// Thinking offers the efforts the model accepts (detected from the provider's
// model list, else by its id); the context limit offers Full and the usual caps
// below the model's window. Both are saved on the provider's model record, so
// they hold for every conversation with that model.

import type { AgentModelOption, AgentModelSettings } from "../../workbench/agent/agentTypes";
import { useEffect, useRef, useState } from "react";
import { ComposerMenu, StepSlider } from "./ComposerMenu";

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
const CAPS = [64_000, 128_000, 256_000, 512_000, 768_000];
/** The server summarizes here unless a limit is chosen (WORKING_BUDGET_TOKENS). */
const DEFAULT_BUDGET = 200_000;

function tokens(value: number): string {
  return value >= ONE_MILLION ? `${+(value / ONE_MILLION).toFixed(1)}M` : `${Math.round(value / 1000)}K`;
}

/** The model's own window, as configured or detected. */
export function modelWindow(model: AgentModelOption): number | null {
  return model.context_window_tokens ?? (model.supports_1m ? ONE_MILLION : null);
}

/** Lowest to highest: the usual caps, the default working budget, and the model's whole window. */
export function limitOptions(model: AgentModelOption): { value: string; label: string }[] {
  const window = modelWindow(model);
  if (window === null) return [];
  if (window <= DEFAULT_BUDGET) {
    return [...CAPS.filter((cap) => cap < window).map((cap) => ({ value: String(cap), label: tokens(cap) })),
      { value: "auto", label: `Full ${tokens(window)}` }];
  }
  const below = CAPS.filter((cap) => cap < DEFAULT_BUDGET).map((cap) => ({ value: String(cap), label: tokens(cap) }));
  const above = CAPS.filter((cap) => cap > DEFAULT_BUDGET && cap < window).map((cap) => ({ value: String(cap), label: tokens(cap) }));
  return [...below, { value: "auto", label: `Auto ${tokens(DEFAULT_BUDGET)}` }, ...above,
    { value: String(window), label: `Full ${tokens(window)}` }];
}

/** Scrolls inside the sheet, opens on the current model, and filters a long list. */
function ModelList({ model, options, onSelect }: {
  model: string;
  options: AgentModelOption[];
  onSelect: (requestModel: string) => void;
}) {
  const [query, setQuery] = useState("");
  const current = useRef<HTMLButtonElement | null>(null);
  useEffect(() => { current.current?.scrollIntoView?.({ block: "nearest" }); }, []);
  const needle = query.trim().toLowerCase();
  const shown = needle
    ? options.filter((option) => `${option.display_name} ${option.request_model}`.toLowerCase().includes(needle))
    : options;
  return (
    <div className="ws-menu__section">
      {options.length > 8 && (
        <input
          className="ws-menu__search"
          type="search"
          aria-label="Filter models"
          placeholder="Filter models"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      )}
      <div className="ws-menu__scroll" role="radiogroup" aria-label="Model">
        {shown.map((option) => (
          <button
            key={option.request_model}
            ref={option.request_model === model ? current : undefined}
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
    </div>
  );
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
      {effort && <span className="ws-menu__label-sub">{EFFORT_NAME[effort]}</span>}
    </span>
  );
  return (
    <ComposerMenu label={label} title={`Model: ${name}`} disabled={disabled || options.length === 0} className="ws-model-menu">
      {() => (
        <>
          <ModelList model={model} options={options} onSelect={onSelect} />
          {current && onSettings && (efforts.length > 0 || limits.length > 1) && (
            <div className="ws-menu__section ws-menu__section--settings">
              {efforts.length > 0 && effort && (
                <StepSlider
                  label="Thinking"
                  options={efforts.map((value) => ({ value, label: EFFORT_NAME[value] }))}
                  value={effort}
                  onChange={(value) => onSettings(current.request_model, { reasoning_effort: value })}
                />
              )}
              {limits.length > 1 && (
                <StepSlider
                  label="Context"
                  title="The conversation is summarized near this size. Lower is faster and cheaper; higher remembers more."
                  options={limits}
                  value={current.context_limit_tokens ? String(current.context_limit_tokens) : "auto"}
                  onChange={(value) => onSettings(current.request_model, {
                    context_limit_tokens: value === "auto" ? null : Number(value),
                  })}
                />
              )}
            </div>
          )}
        </>
      )}
    </ComposerMenu>
  );
}
