// v1.9.1 — one control for how far the Agent may go on its own. It replaces the
// "Mode" select (ask / auto) and the "Review first" toggle (proposal_only /
// auto_read_only), which together had three meaningful states. Shift+Tab in the
// composer cycles them, as in Claude Code.

import { ComposerMenu } from "./ComposerMenu";

export type AgentMode = "review" | "read_only" | "auto";
type ExecutionMode = "ask" | "auto";
type ExecutionPolicy = "auto_read_only" | "proposal_only";

export const AGENT_MODES: { id: AgentMode; name: string; short: string; description: string }[] = [
  { id: "review", name: "Review every step", short: "Review", description: "Every step waits for your OK." },
  { id: "read_only", name: "Run read-only analyses", short: "Read-only", description: "Analyses that change nothing run at once; changes wait for your OK." },
  { id: "auto", name: "Auto within approved plan", short: "Auto", description: "Runs the steps of the plan you approved, without asking each time." },
];

export interface ModeControls {
  executionMode?: ExecutionMode;
  executionPolicy?: ExecutionPolicy;
  setExecutionMode?: (mode: ExecutionMode) => void;
  setExecutionPolicy?: (policy: ExecutionPolicy) => void;
}

export function currentMode(agent: ModeControls): AgentMode {
  if (agent.executionMode === "auto" && agent.executionPolicy !== "proposal_only") return "auto";
  return agent.executionPolicy === "auto_read_only" ? "read_only" : "review";
}

/** The modes this conversation offers: auto needs an execution mode, read-only a policy. */
export function availableModes(agent: ModeControls): AgentMode[] {
  return AGENT_MODES.map((mode) => mode.id).filter((id) =>
    id === "auto" ? Boolean(agent.setExecutionMode) : id === "read_only" ? Boolean(agent.setExecutionPolicy) : true);
}

export function applyMode(agent: ModeControls, mode: AgentMode): void {
  if (mode === "auto") {
    agent.setExecutionMode?.("auto");
    agent.setExecutionPolicy?.("auto_read_only");
    return;
  }
  agent.setExecutionMode?.("ask");
  agent.setExecutionPolicy?.(mode === "read_only" ? "auto_read_only" : "proposal_only");
}

export function cycleMode(agent: ModeControls): void {
  const modes = availableModes(agent);
  if (modes.length < 2) return;
  applyMode(agent, modes[(modes.indexOf(currentMode(agent)) + 1) % modes.length]);
}

export function AgentModeMenu({ agent, disabled }: { agent: ModeControls; disabled?: boolean }) {
  const modes = availableModes(agent);
  if (modes.length < 2) return null;
  const mode = currentMode(agent);
  const active = AGENT_MODES.find((item) => item.id === mode)!;
  return (
    <ComposerMenu
      label={<span className="ws-menu__label-main" data-mode={mode}>{active.short}</span>}
      title={`Mode: ${active.name} (Shift+Tab to switch)`}
      disabled={disabled}
      className="ws-mode-menu"
    >
      {(close) => (
        <div className="ws-menu__section" role="radiogroup" aria-label="Mode">
          {AGENT_MODES.filter((item) => modes.includes(item.id)).map((item) => (
            <button
              key={item.id}
              type="button"
              role="radio"
              aria-checked={item.id === mode}
              className="ws-menu__item ws-menu__item--described"
              onClick={() => {
                applyMode(agent, item.id);
                close();
              }}
            >
              <span className="ws-menu__check" aria-hidden="true">{item.id === mode ? "✓" : ""}</span>
              <span>
                <span className="ws-menu__item-name">{item.name}</span>
                <span className="ws-menu__item-description">{item.description}</span>
              </span>
            </button>
          ))}
          <p className="ws-menu__hint">Shift+Tab in the message box switches modes.</p>
        </div>
      )}
    </ComposerMenu>
  );
}
