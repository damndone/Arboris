import type { DomainMemoryPreferences } from "./domainMemoryContracts";

export interface DomainMemoryControlsProps {
  preferences: DomainMemoryPreferences;
  onChange: (preferences: DomainMemoryPreferences) => void;
  disabled?: boolean;
}

export function DomainMemoryControls({ preferences, onChange, disabled = false }: DomainMemoryControlsProps) {
  const enabled =
    preferences.cross_project_domain_memory_use ||
    preferences.cross_project_domain_memory_iteration;

  return (
    <section className="nb-memory-controls" data-testid="domain-memory-controls" aria-label="Domain memory controls">
      <header className="nb-context-header">
        <span>
          <span className="nb-label">Planning controls</span>
          <span>{` · Cross-project memory · Memory ${enabled ? "on" : "off"}`}</span>
        </span>
        <span>hints only · no automatic execution</span>
      </header>
      <div className="nb-memory-toggle-row">
        <label>
          <input
            data-testid="domain-memory-use"
            type="checkbox"
            role="switch"
            className="nb-memory-switch"
            checked={preferences.cross_project_domain_memory_use}
            disabled={disabled}
            onChange={(event) => onChange({ ...preferences, cross_project_domain_memory_use: event.target.checked })}
          />
          Use approved hints
        </label>
        <label>
          <input
            data-testid="domain-memory-iteration"
            type="checkbox"
            role="switch"
            className="nb-memory-switch"
            checked={preferences.cross_project_domain_memory_iteration}
            disabled={disabled}
            onChange={(event) => onChange({ ...preferences, cross_project_domain_memory_iteration: event.target.checked })}
          />
          Suggest bounded memory candidates
        </label>
      </div>
    </section>
  );
}
