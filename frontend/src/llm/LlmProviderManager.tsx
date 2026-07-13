import { useEffect, useState } from "react";
import { LlmProviderEditor } from "./LlmProviderEditor";
import {
  activateLlmProvider,
  deleteLlmProvider,
  fetchLlmProviders,
  probeLlmProvider,
} from "./llmApi";
import type { LlmProvider } from "./llmTypes";

export interface LlmProviderManagerProps {
  onBack: () => void;
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
  overflowY: "auto",
  overscrollBehavior: "contain",
  WebkitOverflowScrolling: "touch",
  width: "100%",
  boxSizing: "border-box",
  padding: "28px clamp(20px, 5vw, 72px)",
  background: "var(--bg-canvas, #101012)",
  color: "var(--label, #f5f5f7)",
};

const buttonStyle: React.CSSProperties = {
  border: "1px solid var(--separator, #3a3a3c)",
  borderRadius: 8,
  padding: "7px 12px",
  background: "var(--bg-card-2, rgba(255,255,255,0.06))",
  color: "var(--label, #f5f5f7)",
  cursor: "pointer",
};

export function LlmProviderManager({ onBack }: LlmProviderManagerProps) {
  const [providers, setProviders] = useState<LlmProvider[]>([]);
  const [activeProviderId, setActiveProviderId] = useState<string | null>(null);
  const [editingProvider, setEditingProvider] = useState<LlmProvider | null | undefined>(undefined);
  const [isCopy, setIsCopy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [probeStates, setProbeStates] = useState<Record<string, ProbeState>>({});

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
      <header style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 28 }}>
        <button type="button" onClick={onBack} style={{ ...buttonStyle, background: "transparent" }}>
          ← Back
        </button>
        <h1 id="llm-provider-manager-title" style={{ margin: 0, fontFamily: "var(--font-serif, serif)", fontSize: 25 }}>
          LLM Providers
        </h1>
        <button type="button" onClick={() => { setIsCopy(false); setEditingProvider(null); }} style={{ ...buttonStyle, marginLeft: "auto" }}>
          + Add provider
        </button>
      </header>

      {error && <div role="alert" data-testid="llm-provider-manager-error" style={{ color: "var(--danger, #ff453a)", marginBottom: 14 }}>{error}</div>}
      {status && <div aria-live="polite" data-testid="llm-provider-manager-status" style={{ color: "var(--green, #30d158)", marginBottom: 14 }}>{status}</div>}
      {loading && <div aria-live="polite">Loading providers…</div>}
      {!loading && providers.length === 0 && <div style={{ color: "var(--label-secondary, #98989d)" }}>No providers configured.</div>}

      <div data-testid="llm-provider-list" style={{ display: "grid", gap: 12 }}>
        {providers.map((provider) => {
          const isActive = provider.id === activeProviderId;
          const probeState = probeStates[provider.id] ?? "idle";
          const probeLabel = probeState === "success" ? "Reachable" : probeState === "error" ? "Failed" : probeState === "loading" ? "Testing…" : "Not tested";
          return (
            <article key={provider.id} style={{ border: "1px solid var(--separator, #3a3a3c)", borderRadius: 12, padding: 16, background: "var(--bg-card-2, rgba(255,255,255,0.04))" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <strong>{provider.name}</strong>
                <span data-testid={`llm-provider-active-${provider.id}`} style={{ color: isActive ? "var(--green, #30d158)" : "var(--label-tertiary, #8e8e93)" }}>
                  {isActive ? "Active" : "Available"}
                </span>
                <span style={{ color: "var(--label-secondary, #98989d)" }}>{provider.key_present ? "API key configured" : "API key missing"}</span>
                <span style={{ color: "var(--label-secondary, #98989d)", fontFamily: "var(--font-mono, monospace)" }}>{provider.model || "No default model"}</span>
              </div>
              <div style={{ marginTop: 8, color: "var(--label-secondary, #98989d)", fontSize: 12 }}>Base URL: {provider.base_url || "—"}</div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
                <span style={{ color: probeState === "success" ? "var(--green, #30d158)" : probeState === "error" ? "var(--danger, #ff453a)" : "var(--label-tertiary, #8e8e93)" }}>Probe: {probeLabel}</span>
                {!isActive && <button type="button" data-testid={`llm-provider-activate-${provider.id}`} disabled={busyId === provider.id} onClick={() => void activate(provider.id)} style={buttonStyle}>Use</button>}
                {isActive && <button type="button" data-testid={`llm-provider-activate-${provider.id}`} disabled style={buttonStyle}>Active</button>}
                <button type="button" onClick={() => void probe(provider.id)} disabled={probeState === "loading"} style={buttonStyle}>Test connection</button>
                <button type="button" data-testid={`llm-provider-edit-${provider.id}`} onClick={() => setEditingProvider(provider)} style={buttonStyle}>Edit</button>
                <button type="button" data-testid={`llm-provider-copy-${provider.id}`} onClick={() => copy(provider)} style={buttonStyle}>Copy</button>
                <button type="button" data-testid={`llm-provider-delete-${provider.id}`} disabled={busyId === provider.id} onClick={() => void remove(provider)} style={{ ...buttonStyle, color: "var(--danger, #ff453a)" }}>Delete</button>
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
