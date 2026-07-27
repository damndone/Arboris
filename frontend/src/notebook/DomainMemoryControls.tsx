import type { DomainMemoryPreferences } from "./domainMemoryContracts";

export interface DomainMemoryControlsProps {
  preferences: DomainMemoryPreferences;
  onChange: (preferences: DomainMemoryPreferences) => void;
  disabled?: boolean;
}

export function DomainMemoryControls({ preferences, onChange, disabled = false }: DomainMemoryControlsProps) {
  return (
    <section className="nb-context-slice" data-testid="domain-memory-controls" aria-label="Domain memory controls">
      <header className="nb-context-header">
        <span className="nb-label">Cross-project memory</span>
        <span>default off · hints only · no automatic execution</span>
      </header>
      <label>
        <input
          data-testid="domain-memory-use"
          type="checkbox"
          checked={preferences.cross_project_domain_memory_use}
          disabled={disabled}
          onChange={(event) => onChange({ ...preferences, cross_project_domain_memory_use: event.target.checked })}
        />
        Use approved domain-memory hints for this planning context
      </label>
      <label>
        <input
          data-testid="domain-memory-iteration"
          type="checkbox"
          checked={preferences.cross_project_domain_memory_iteration}
          disabled={disabled}
          onChange={(event) => onChange({ ...preferences, cross_project_domain_memory_iteration: event.target.checked })}
        />
        Allow bounded candidate suggestions after an explicit review point
      </label>
    </section>
  );
}
