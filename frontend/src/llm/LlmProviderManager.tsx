import { useEffect, useState } from "react";
import { AppearanceSettings } from "../workspace/AppearanceSettings";
import { LlmProviderEditor } from "./LlmProviderEditor";
import { AgentExtensionsPanel } from "../workbench/AgentExtensionsPanel";
import { MemorySettingsPanel } from "../workbench/MemorySettingsPanel";
import { AgentInstructionsPanel } from "../workbench/AgentInstructionsPanel";
import { AgentPermissionsPanel } from "../workbench/AgentPermissionsPanel";
import {
  activateLlmProvider,
  deleteLlmProvider,
  detectLlmProviderModels,
  fetchLlmProviders,
  probeLlmProvider,
  refreshLlmProviderModels,
  updateLlmProvider,
} from "./llmApi";
import type { LlmProvider } from "./llmTypes";
import "./llmProviders.css";

export interface LlmProviderManagerProps {
  onBack: () => void;
  projectRoot?: string;
}

type ProbeState = "idle" | "loading" | "success" | "error";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Request failed";
}

const shellStyle: React.CSSProperties = {
  flex: "1 1 0",
  height: "100%",
  maxHeight: "100%",
  minHeight: 0,
  minWidth: 0,
  overflowY: "auto",
  overscrollBehavior: "contain",
  WebkitOverflowScrolling: "touch",
  width: "100%",
  boxSizing: "border-box",
  padding: "28px clamp(20px, 5vw, 72px)",
  background: "var(--bg-canvas)",
  color: "var(--label)",
};

const buttonStyle: React.CSSProperties = {
  border: "1px solid var(--separator)",
  borderRadius: 8,
  padding: "7px 12px",
  background: "var(--bg-card-2)",
  color: "var(--label)",
  cursor: "pointer",
};

const settingsSectionButtonStyle = (active: boolean): React.CSSProperties => ({
  ...buttonStyle,
  background: active ? "var(--tint-fill)" : "var(--bg-card-2)",
  borderColor: active ? "var(--tint-fill)" : "var(--separator)",
  color: active ? "var(--on-tint)" : "var(--label)",
  boxShadow: active ? "var(--shadow-1)" : "none",
});

export function LlmProviderManager({ onBack, projectRoot }: LlmProviderManagerProps) {
  const [providers, setProviders] = useState<LlmProvider[]>([]);
  const [activeProviderId, setActiveProviderId] = useState<string | null>(null);
  const [editingProvider, setEditingProvider] = useState<LlmProvider | null | undefined>(undefined);
  const [isCopy, setIsCopy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [probeStates, setProbeStates] = useState<Record<string, ProbeState>>({});
  const [settingsSection, setSettingsSection] = useState<"providers" | "instructions" | "permissions" | "memory" | "extensions" | "appearance">("providers");

  async function refreshProviders() {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchLlmProviders();
      setProviders(result.providers);
      setActiveProviderId(result.active_provider_id);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshProviders();
  }, []);

  async function activate(providerId: string) {
    setBusyId(providerId);
    setError(null);
    setStatus(null);
    try {
      await activateLlmProvider(providerId);
      await refreshProviders();
      setStatus("Provider activated");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusyId(null);
    }
  }

  async function remove(provider: LlmProvider) {
    if (!window.confirm(`Delete provider ${provider.name}?`)) return;
    setBusyId(provider.id);
    setError(null);
    setStatus(null);
    try {
      await deleteLlmProvider(provider.id);
      await refreshProviders();
      setStatus("Provider deleted");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusyId(null);
    }
  }

  async function probe(providerId: string) {
    setProbeStates((current) => ({ ...current, [providerId]: "loading" }));
    setError(null);
    try {
      await probeLlmProvider(providerId);
      setProbeStates((current) => ({ ...current, [providerId]: "success" }));
    } catch (requestError) {
      setProbeStates((current) => ({ ...current, [providerId]: "error" }));
      setError(errorMessage(requestError));
    }
  }

  async function refreshModels(providerId: string, capabilitiesOnly = false) {
    setBusyId(providerId);
    setError(null);
    setStatus(null);
    try {
      const updated = await (capabilitiesOnly ? detectLlmProviderModels : refreshLlmProviderModels)(providerId);
      setProviders((current) => current.map((provider) => (
        provider.id === updated.id ? updated : provider
      )));
      setStatus(capabilitiesOnly ? `${updated.name} model capabilities checked` : `${updated.name} models refreshed`);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusyId(null);
    }
  }

  async function changeModel(providerId: string, model: string) {
    setBusyId(providerId);
    setError(null);
    setStatus(null);
    try {
      const updated = await updateLlmProvider(providerId, { model });
      setProviders((current) => current.map((provider) => (
        provider.id === updated.id ? updated : provider
      )));
      setStatus(`Model switched to ${updated.model}`);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusyId(null);
    }
  }

  function copy(provider: LlmProvider) {
    const baseId = `${provider.id}-copy`;
    let copyId = baseId;
    let suffix = 2;
    while (providers.some((candidate) => candidate.id === copyId)) {
      copyId = `${baseId}-${suffix}`;
      suffix += 1;
    }
    setIsCopy(true);
    setEditingProvider({
      ...provider,
      id: copyId,
      name: `${provider.name} Copy`,
      key_present: false,
      models: provider.models.map((model) => ({ ...model })),
    });
  }

  if (editingProvider !== undefined) {
    return (
      <LlmProviderEditor
        provider={editingProvider}
        isCopy={isCopy}
        onBack={() => { setEditingProvider(undefined); setIsCopy(false); }}
        onSaved={() => {
          setEditingProvider(undefined);
          setIsCopy(false);
          void refreshProviders();
        }}
      />
    );
  }

  return (
    <div role="dialog" aria-labelledby="llm-provider-manager-title" data-testid="llm-provider-manager" style={shellStyle}>
      <header style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 14, marginBottom: 28 }}>
        <button type="button" onClick={onBack} style={{ ...buttonStyle, background: "transparent" }}>
          ← Back
        </button>
        <h1 id="llm-provider-manager-title" style={{ margin: 0, fontFamily: "var(--font-serif, serif)", fontSize: 25 }}>
          Settings
        </h1>
        {settingsSection === "providers" ? <div style={{ display: "flex", gap: 8, marginLeft: "auto" }}>
          <button type="button" onClick={() => void refreshProviders()} disabled={loading || busyId !== null} style={buttonStyle}>
            Reload providers
          </button>
          <button type="button" onClick={() => { setIsCopy(false); setEditingProvider(null); }} style={buttonStyle}>
            + Add provider
          </button>
        </div> : null}
      </header>

      <nav aria-label="Settings sections" style={{ display: "flex", flexWrap: "wrap", gap: 8, margin: "0 0 20px" }}>
        <button type="button" aria-pressed={settingsSection === "providers"} onClick={() => setSettingsSection("providers")} style={settingsSectionButtonStyle(settingsSection === "providers")}>LLM providers</button>
        {projectRoot ? <button type="button" aria-pressed={settingsSection === "instructions"} onClick={() => setSettingsSection("instructions")} style={settingsSectionButtonStyle(settingsSection === "instructions")}>Agent instructions</button> : null}
        {projectRoot ? <button type="button" aria-pressed={settingsSection === "permissions"} onClick={() => setSettingsSection("permissions")} style={settingsSectionButtonStyle(settingsSection === "permissions")}>Agent permissions</button> : null}
        {projectRoot ? <button type="button" aria-pressed={settingsSection === "memory"} onClick={() => setSettingsSection("memory")} style={settingsSectionButtonStyle(settingsSection === "memory")}>Memory</button> : null}
        {projectRoot ? <button type="button" aria-pressed={settingsSection === "extensions"} onClick={() => setSettingsSection("extensions")} style={settingsSectionButtonStyle(settingsSection === "extensions")}>Tools and hooks</button> : null}
        <button type="button" aria-pressed={settingsSection === "appearance"} onClick={() => setSettingsSection("appearance")} style={settingsSectionButtonStyle(settingsSection === "appearance")}>Appearance</button>
      </nav>

      {settingsSection === "permissions" && projectRoot ? <AgentPermissionsPanel key={projectRoot} projectRoot={projectRoot} /> :
        settingsSection === "extensions" && projectRoot ? <AgentExtensionsPanel projectRoot={projectRoot} /> : settingsSection === "instructions" && projectRoot ? <AgentInstructionsPanel projectRoot={projectRoot} /> : settingsSection === "memory" && projectRoot ? <MemorySettingsPanel projectRoot={projectRoot} /> : settingsSection === "appearance" ? <AppearanceSettings /> : <>

      {error && <div role="alert" data-testid="llm-provider-manager-error" style={{ color: "var(--status-fails-fg)", marginBottom: 14 }}>{error}</div>}
      {status && <div aria-live="polite" data-testid="llm-provider-manager-status" style={{ color: "var(--green)", marginBottom: 14 }}>{status}</div>}
      {loading && <div aria-live="polite">Loading providers…</div>}
      {!loading && providers.length === 0 && <div style={{ color: "var(--label-secondary)" }}>No providers configured.</div>}

      <div data-testid="llm-provider-list" style={{ display: "grid", gap: 12 }}>
        {providers.map((provider) => {
          const isActive = provider.id === activeProviderId;
          const probeState = probeStates[provider.id] ?? "idle";
          const probeLabel = probeState === "success" ? "Reachable" : probeState === "error" ? "Failed" : probeState === "loading" ? "Testing…" : "Not tested";
          const modelOptions = provider.models.some((model) => model.request_model === provider.model)
            ? provider.models
            : [
                {
                  display_name: provider.model || "Current model",
                  request_model: provider.model,
                  context_window_tokens: null,
                  supports_1m: false,
                },
                ...provider.models,
              ];
          return (
            <article key={provider.id} aria-label={`${provider.name} provider`} className="llm-provider-card" data-active={isActive}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <strong style={{ overflowWrap: "anywhere" }}>{provider.name}</strong>
                <span className="llm-provider-status" data-testid={`llm-provider-active-${provider.id}`}>
                  {isActive ? "Active" : "Available"}
                </span>
                <span style={{ color: "var(--label-secondary)" }}>{provider.key_present ? "API key configured" : "API key missing"}</span>
                {modelOptions.length > 0 ? (
                  <select
                    aria-label={`Model for ${provider.name}`}
                    value={provider.model}
                    disabled={busyId === provider.id}
                    onChange={(event) => void changeModel(provider.id, event.target.value)}
                    style={{
                      maxWidth: "min(100%, 320px)",
                      minWidth: 0,
                      border: "1px solid var(--separator)",
                      borderRadius: 6,
                      padding: "3px 6px",
                      background: "var(--bg-card-2)",
                      color: "var(--label)",
                      fontFamily: "var(--font-mono, monospace)",
                      fontSize: 12,
                    }}
                  >
                    {modelOptions.map((model) => (
                      <option key={model.request_model} value={model.request_model}>
                        {model.display_name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span style={{ color: "var(--label-secondary)", fontFamily: "var(--font-mono, monospace)" }}>
                    {provider.model || "No default model"}
                  </span>
                )}
              </div>
              <div style={{ marginTop: 8, color: "var(--label-secondary)", fontSize: 12, overflowWrap: "anywhere" }}>Base URL: {provider.base_url || "—"}</div>
              <div
                data-testid={`llm-provider-models-${provider.id}`}
                className="llm-provider-models"
                role="group"
                aria-label={`Mapped models for ${provider.name}`}
              >
                {provider.models.length > 0
                  ? provider.models.map((model) => (
                    <button key={model.request_model} type="button" className="llm-model-card"
                      aria-label={`Use model ${model.display_name}`}
                      aria-pressed={model.request_model === provider.model}
                      title={`${model.display_name}\n${model.request_model}${model.context_window_tokens !== null ? `\nContext: ${model.context_window_tokens.toLocaleString("en-US")} tokens` : ""}`}
                      disabled={busyId === provider.id}
                      onClick={() => void changeModel(provider.id, model.request_model)}>
                      {model.request_model === provider.model && <span aria-hidden="true">✓</span>}
                      <span className="llm-model-card-name">{model.display_name}</span>
                    </button>
                  ))
                  : <span>No mapped models</span>}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
                <span style={{ color: probeState === "success" ? "var(--green)" : probeState === "error" ? "var(--status-fails-fg)" : "var(--label-tertiary)" }}>Probe: {probeLabel}</span>
                {!isActive && <button type="button" data-testid={`llm-provider-activate-${provider.id}`} disabled={busyId === provider.id} onClick={() => void activate(provider.id)} style={buttonStyle}>Use</button>}
                {isActive && <button type="button" data-testid={`llm-provider-activate-${provider.id}`} disabled style={buttonStyle}>Active</button>}
                <button type="button" onClick={() => void probe(provider.id)} disabled={probeState === "loading"} style={buttonStyle}>Test connection</button>
                <button type="button" data-testid={`llm-provider-refresh-models-${provider.id}`} onClick={() => void refreshModels(provider.id)} disabled={busyId === provider.id} style={buttonStyle}>Refresh models</button>
                <button type="button" data-testid={`llm-provider-detect-models-${provider.id}`}
                  title="Check provider-reported context limits, reasoning options, and vision for the mapped models"
                  onClick={() => void refreshModels(provider.id, true)} disabled={busyId === provider.id}
                  style={buttonStyle}>Detect capabilities</button>
                <button type="button" data-testid={`llm-provider-edit-${provider.id}`} onClick={() => setEditingProvider(provider)} style={buttonStyle}>Edit</button>
                <button type="button" data-testid={`llm-provider-configure-${provider.id}`} onClick={() => setEditingProvider(provider)} style={buttonStyle}>Configure</button>
                <button type="button" data-testid={`llm-provider-copy-${provider.id}`} onClick={() => copy(provider)} style={buttonStyle}>Copy</button>
                <button type="button" data-testid={`llm-provider-delete-${provider.id}`} disabled={busyId === provider.id} onClick={() => void remove(provider)} style={{ ...buttonStyle, color: "var(--status-fails-fg)" }}>Delete</button>
              </div>
            </article>
          );
        })}
      </div>
      </>}
    </div>
  );
}
