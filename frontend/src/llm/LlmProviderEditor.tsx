import { useMemo, useState } from "react";
import type { ChangeEvent, CSSProperties } from "react";
import {
  createLlmProvider,
  probeLlmProvider,
  refreshLlmProviderModels,
  updateLlmProvider,
} from "./llmApi";
import { providerPresets } from "./providerPresets";
import type { LlmModel, LlmProvider, ProviderUpsertInput } from "./llmTypes";

export interface LlmProviderEditorProps {
  provider?: LlmProvider | null;
  isCopy?: boolean;
  onSaved: (provider: LlmProvider) => void;
  onBack: () => void;
}

type FieldErrors = Partial<Record<"id" | "name" | "baseUrl" | "model", string>>;

const providerIdPattern = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

const shellStyle: CSSProperties = {
  minHeight: "100vh",
  width: "100%",
  boxSizing: "border-box",
  padding: "28px clamp(20px, 5vw, 72px)",
  background: "var(--bg-canvas, #101012)",
  color: "var(--label, #f5f5f7)",
};

const inputStyle: CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  marginTop: 6,
  padding: "9px 10px",
  border: "1px solid var(--separator, #3a3a3c)",
  borderRadius: 7,
  background: "var(--bg-card-2, rgba(255,255,255,0.05))",
  color: "var(--label, #f5f5f7)",
};

const actionStyle: CSSProperties = {
  border: "1px solid var(--separator, #3a3a3c)",
  borderRadius: 8,
  padding: "8px 13px",
  background: "var(--bg-card-2, rgba(255,255,255,0.06))",
  color: "var(--label, #f5f5f7)",
  cursor: "pointer",
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Request failed";
}

function initialModels(provider?: LlmProvider | null): LlmModel[] {
  return provider?.models ? provider.models.map((model) => ({ ...model })) : [];
}

function formatContextWindow(value: number | null): string {
  return value === null ? "—" : value.toLocaleString("en-US");
}

export function LlmProviderEditor({ provider, isCopy = false, onSaved, onBack }: LlmProviderEditorProps) {
  const isEditing = Boolean(provider && !isCopy);
  const [id, setId] = useState(provider?.id ?? "");
  const [name, setName] = useState(provider?.name ?? "");
  const [icon, setIcon] = useState(provider?.icon ?? "");
  const [notes, setNotes] = useState(provider?.notes ?? "");
  const [websiteUrl, setWebsiteUrl] = useState(provider?.website_url ?? "");
  const [baseUrl, setBaseUrl] = useState(provider?.base_url ?? "");
  const [apiKey, setApiKey] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [clearApiKey, setClearApiKey] = useState(false);
  const [model, setModel] = useState(provider?.model ?? "");
  const [timeout, setTimeoutValue] = useState(String(provider?.timeout_s ?? 60));
  const [models, setModels] = useState<LlmModel[]>(() => initialModels(provider));
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [requestError, setRequestError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [probeLoading, setProbeLoading] = useState(false);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [probeMessage, setProbeMessage] = useState<string | null>(null);
  const [modelsMessage, setModelsMessage] = useState<string | null>(null);

  const preview = useMemo(() => JSON.stringify({
    id: id.trim(),
    name: name.trim(),
    icon: icon.trim(),
    notes: notes.trim(),
    website_url: websiteUrl.trim(),
    base_url: baseUrl.trim(),
    model: model.trim(),
    timeout_s: Number(timeout) || 60,
    models: models.map(({ display_name, request_model, context_window_tokens, supports_1m }) => ({ display_name, request_model, context_window_tokens, supports_1m })),
  }, null, 2), [baseUrl, icon, id, model, models, name, notes, timeout, websiteUrl]);

  function validate(): FieldErrors {
    const errors: FieldErrors = {};
    if (!isEditing) {
      if (!id.trim()) errors.id = "Provider ID is required";
      else if (!providerIdPattern.test(id.trim())) errors.id = "Provider ID must be a route-safe slug";
    }
    if (!name.trim()) errors.name = "Provider name is required";
    if (!baseUrl.trim()) {
      errors.baseUrl = "Base URL is required";
    } else {
      try {
        const url = new URL(baseUrl.trim());
        if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("invalid protocol");
      } catch {
        errors.baseUrl = "Base URL must be an absolute http(s) URL";
      }
    }
    if (!model.trim()) errors.model = "Default model is required";
    return errors;
  }

  function handlePreset(event: ChangeEvent<HTMLSelectElement>) {
    const preset = providerPresets.find((candidate) => candidate.name === event.target.value);
    if (!preset) return;
    setName(preset.name);
    setBaseUrl(preset.baseUrl);
  }

  function updateModel(index: number, patch: Partial<LlmModel>) {
    setModels((current) => current.map((entry, entryIndex) => entryIndex === index ? { ...entry, ...patch } : entry));
  }

  async function handleProbe() {
    if (!isEditing || !provider?.id) {
      setProbeMessage("Save the provider before testing its connection");
      return;
    }
    setProbeLoading(true);
    setProbeMessage(null);
    setRequestError(null);
    try {
      await probeLlmProvider(provider.id);
      setProbeMessage("Connection successful");
    } catch (error) {
      setProbeMessage(errorMessage(error));
    } finally {
      setProbeLoading(false);
    }
  }

  async function handleRefreshModels() {
    if (!isEditing || !provider?.id) {
      setModelsMessage("Save the provider before refreshing models");
      return;
    }
    setModelsLoading(true);
    setModelsMessage(null);
    setRequestError(null);
    try {
      const result = await refreshLlmProviderModels(provider.id);
      setModels(result.models.map((entry) => ({ ...entry })));
      setModel(result.model);
      setModelsMessage("Models refreshed");
    } catch (error) {
      setModelsMessage(errorMessage(error));
    } finally {
      setModelsLoading(false);
    }
  }

  async function handleSave() {
    const errors = validate();
    setFieldErrors(errors);
    setRequestError(null);
    setSuccess(null);
    if (Object.keys(errors).length > 0) return;

    const payload: ProviderUpsertInput = {
      ...(isEditing ? {} : { id: id.trim() }),
      name: name.trim(),
      icon: icon.trim(),
      notes: notes.trim(),
      website_url: websiteUrl.trim() || null,
      base_url: baseUrl.trim(),
      model: model.trim(),
      timeout_s: Number(timeout) || 60,
      models,
    };
    if (apiKey.trim()) payload.api_key = apiKey.trim();
    if (clearApiKey) payload.clear_api_key = true;

    setSaving(true);
    try {
      const saved = isEditing && provider?.id
        ? await updateLlmProvider(provider.id, payload)
        : await createLlmProvider(payload);
      setSuccess("Provider saved");
      onSaved(saved);
    } catch (error) {
      setRequestError(errorMessage(error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div role="dialog" aria-labelledby="llm-provider-editor-title" data-testid="llm-provider-editor" style={shellStyle}>
      <header style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 24 }}>
        <button type="button" onClick={onBack} style={{ ...actionStyle, background: "transparent" }}>← Back</button>
        <h1 id="llm-provider-editor-title" style={{ margin: 0, fontFamily: "var(--font-serif, serif)", fontSize: 25 }}>{isEditing ? "Edit provider" : "Add provider"}</h1>
        <button type="button" onClick={() => void handleSave()} disabled={saving} style={{ ...actionStyle, marginLeft: "auto", background: "var(--tint, #0a84ff)", color: "#fff" }}>{saving ? "Saving…" : "Save"}</button>
        <button type="button" onClick={onBack} disabled={saving} style={actionStyle}>Cancel</button>
      </header>

      {requestError && <div role="alert" data-testid="llm-provider-editor-error" style={{ color: "var(--danger, #ff453a)", marginBottom: 14 }}>{requestError}</div>}
      {success && <div aria-live="polite" data-testid="llm-provider-editor-success" style={{ color: "var(--green, #30d158)", marginBottom: 14 }}>{success}</div>}

      <main style={{ maxWidth: 980, margin: "0 auto", display: "grid", gap: 18 }}>
        <section style={{ padding: 20, border: "1px solid var(--separator, #3a3a3c)", borderRadius: 14, background: "var(--bg-card-2, rgba(255,255,255,0.04))" }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16 }}>
            <label>Provider preset
              <select aria-label="provider preset" defaultValue="" onChange={handlePreset} style={inputStyle}>
                <option value="">Choose a preset</option>
                {providerPresets.map((preset) => <option key={preset.name} value={preset.name}>{preset.name}</option>)}
              </select>
            </label>
            <label>Provider ID
              <input aria-label="provider id" value={id} readOnly={isEditing} disabled={isEditing} onChange={(event) => setId(event.target.value)} style={inputStyle} />
              {fieldErrors.id && <span style={{ display: "block", marginTop: 5, color: "var(--danger, #ff453a)" }}>{fieldErrors.id}</span>}
            </label>
            <label>Provider name
              <input aria-label="provider name" value={name} onChange={(event) => setName(event.target.value)} style={inputStyle} />
              {fieldErrors.name && <span style={{ display: "block", marginTop: 5, color: "var(--danger, #ff453a)" }}>{fieldErrors.name}</span>}
            </label>
            <label>Icon
              <input aria-label="icon" value={icon} onChange={(event) => setIcon(event.target.value)} style={inputStyle} />
            </label>
            <label style={{ gridColumn: "1 / -1" }}>Notes / context notes
              <textarea aria-label="notes" value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} style={{ ...inputStyle, resize: "vertical" }} />
            </label>
            <label>Website URL
              <input aria-label="website url" value={websiteUrl} onChange={(event) => setWebsiteUrl(event.target.value)} style={inputStyle} />
            </label>
            <label>API Key
              <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                <input aria-label="api key" type={showApiKey ? "text" : "password"} value={apiKey} placeholder={provider?.key_present ? "Leave blank to keep current key" : "Paste an API key"} onChange={(event) => { setApiKey(event.target.value); if (event.target.value) setClearApiKey(false); }} style={{ ...inputStyle, marginTop: 0, flex: 1 }} />
                <button type="button" aria-label={showApiKey ? "Hide API key" : "Show API key"} onClick={() => setShowApiKey((visible) => !visible)} style={actionStyle}>{showApiKey ? "Hide" : "Show"}</button>
              </div>
              {provider?.key_present && <div style={{ marginTop: 6, color: "var(--label-secondary, #98989d)", fontSize: 12 }}>An API key is already configured.</div>}
              {provider?.key_present && <button type="button" aria-label="Clear API key" onClick={() => { setApiKey(""); setClearApiKey(true); }} style={{ ...actionStyle, marginTop: 8, color: "var(--danger, #ff453a)" }}>Clear API key</button>}
              {clearApiKey && <span data-testid="llm-provider-key-cleared" style={{ display: "block", marginTop: 5, color: "var(--danger, #ff453a)" }}>The existing key will be cleared.</span>}
            </label>
          </div>
          <label style={{ display: "block", marginTop: 16 }}>Base URL
            <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
              <input aria-label="base url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} style={{ ...inputStyle, marginTop: 0, flex: 1 }} />
              <button type="button" onClick={() => void handleProbe()} disabled={probeLoading} style={actionStyle}>{probeLoading ? "Testing…" : "Test connection"}</button>
            </div>
            {fieldErrors.baseUrl && <span style={{ display: "block", marginTop: 5, color: "var(--danger, #ff453a)" }}>{fieldErrors.baseUrl}</span>}
            {probeMessage && <span aria-live="polite" style={{ display: "block", marginTop: 5, color: probeMessage === "Connection successful" ? "var(--green, #30d158)" : "var(--danger, #ff453a)" }}>{probeMessage}</span>}
          </label>
        </section>

        <details style={{ padding: 18, border: "1px solid var(--separator, #3a3a3c)", borderRadius: 14, background: "var(--bg-card-2, rgba(255,255,255,0.04))" }}>
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>Advanced options</summary>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 16, marginTop: 16 }}>
            <label>API format
              <select aria-label="api format" disabled value="openai-chat-completions" style={inputStyle}>
                <option value="openai-chat-completions">OpenAI-compatible Chat Completions</option>
              </select>
            </label>
            <label>Authentication
              <select aria-label="authentication" disabled value="authorization-bearer" style={inputStyle}>
                <option value="authorization-bearer">Authorization: Bearer</option>
              </select>
            </label>
            <label>Request timeout (seconds)<input aria-label="request timeout" type="number" min="1" value={timeout} onChange={(event) => setTimeoutValue(event.target.value)} style={inputStyle} /></label>
          </div>
        </details>

        <section style={{ padding: 20, border: "1px solid var(--separator, #3a3a3c)", borderRadius: 14, background: "var(--bg-card-2, rgba(255,255,255,0.04))" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
            <h2 style={{ margin: 0, fontSize: 16 }}>Model mapping</h2>
            <button type="button" onClick={() => void handleRefreshModels()} disabled={modelsLoading} style={{ ...actionStyle, marginLeft: "auto" }}>{modelsLoading ? "Refreshing…" : "Refresh models"}</button>
          </div>
          {modelsMessage && <div aria-live="polite" style={{ color: modelsMessage === "Models refreshed" ? "var(--green, #30d158)" : "var(--danger, #ff453a)", marginBottom: 10 }}>{modelsMessage}</div>}
          <label>Default model
            <input aria-label="default model" value={model} onChange={(event) => setModel(event.target.value)} style={inputStyle} />
            {fieldErrors.model && <span style={{ display: "block", marginTop: 5, color: "var(--danger, #ff453a)" }}>{fieldErrors.model}</span>}
          </label>
          <div style={{ display: "grid", gap: 8, marginTop: 16 }}>
            {models.map((entry, index) => (
              <div key={`${entry.request_model}-${index}`} data-testid={`llm-provider-model-row-${entry.request_model}`} style={{ display: "grid", gridTemplateColumns: "1.2fr 1.2fr 0.8fr auto", gap: 8, alignItems: "center", padding: 10, borderTop: "1px solid var(--separator, #3a3a3c)" }}>
                <input aria-label={`display name ${entry.request_model}`} value={entry.display_name} onChange={(event) => updateModel(index, { display_name: event.target.value })} style={inputStyle} />
                <input aria-label={`request model ${entry.request_model}`} value={entry.request_model} onChange={(event) => updateModel(index, { request_model: event.target.value })} style={inputStyle} />
                <label style={{ fontSize: 12 }}>Context window
                  <input aria-label={`context window ${entry.request_model}`} type="number" value={entry.context_window_tokens ?? ""} onChange={(event) => updateModel(index, { context_window_tokens: event.target.value ? Number(event.target.value) : null })} style={inputStyle} />
                </label>
                <label style={{ fontSize: 12, whiteSpace: "nowrap" }}><input aria-label={`supports 1M ${entry.request_model}`} type="checkbox" checked={entry.supports_1m} onChange={(event) => updateModel(index, { supports_1m: event.target.checked })} /> Supports 1M
                  <div style={{ color: "var(--label-secondary, #98989d)", marginTop: 6 }}>{formatContextWindow(entry.context_window_tokens)} · {entry.supports_1m ? "Yes" : "No"}</div>
                </label>
              </div>
            ))}
          </div>
        </section>

        <section style={{ padding: 20, border: "1px solid var(--separator, #3a3a3c)", borderRadius: 14, background: "var(--bg-card-2, rgba(255,255,255,0.04))" }}>
          <h2 style={{ margin: "0 0 10px", fontSize: 16 }}>Sanitized config preview</h2>
          <pre data-testid="llm-provider-config-preview" style={{ margin: 0, padding: 14, overflow: "auto", background: "var(--bg-canvas, #101012)", color: "var(--label-secondary, #98989d)", fontFamily: "var(--font-mono, monospace)", fontSize: 12 }}>{preview}</pre>
        </section>
      </main>
    </div>
  );
}
