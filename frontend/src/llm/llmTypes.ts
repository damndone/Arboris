export interface LlmModel {
  display_name: string;
  request_model: string;
  context_window_tokens: number | null;
  supports_1m: boolean;
  /** v1.7 G2: model accepts image content — gates the send-the-chart opt-in. */
  supports_vision?: boolean;
}

export interface LlmProvider {
  id: string;
  name: string;
  icon: string;
  notes: string;
  website_url: string | null;
  base_url: string | null;
  model: string;
  timeout_s: number;
  models: LlmModel[];
  key_present: boolean;
}

export interface LlmProvidersResponse {
  active_provider_id: string | null;
  providers: LlmProvider[];
}

export interface LlmConfigInfo {
  configured: boolean;
  base_url: string | null;
  model: string | null;
  key_present: boolean;
  timeout_s: number;
  provider_id: string | null;
  provider_name: string | null;
  source: "local" | "environment" | "none";
  context_window_tokens: number | null;
  supports_1m: boolean;
  /** v1.7 G2: whether the active model can accept the rendered chart image. */
  supports_vision?: boolean;
}

export interface ProviderUpsertInput {
  id?: string;
  name?: string;
  icon?: string;
  notes?: string;
  website_url?: string | null;
  base_url?: string;
  model?: string;
  api_key?: string;
  timeout_s?: number;
  models?: LlmModel[];
  clear_api_key?: boolean;
}

export interface LlmProviderPreset {
  name: string;
  baseUrl: string;
}
