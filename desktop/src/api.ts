const baseUrl = "http://127.0.0.1:8000";

export type Channel = { id: number; handle: string; title?: string; active: boolean; analyst_score?: number };
export type Consensus = { company: string; sentiment: string; confidence: number; buy_count: number; sell_count: number; hold_count: number };
export type AiProvider = "qwen" | "openrouter" | "huggingface" | "openai";
export type SettingsStatus = { openai_configured: boolean; ai_configured: boolean; ai_provider: AiProvider; telegram_configured: boolean; telegram_authorized: boolean; openai_model: string; telegram_session: string; analysis_instructions: string };
export type SettingsInput = { ai_provider?: AiProvider; openai_api_key?: string; openrouter_api_key?: string; huggingface_api_key?: string; qwen_api_key?: string; qwen_base_url?: string; openai_model?: string; analysis_instructions?: string; telegram_api_id?: number; telegram_api_hash?: string; telegram_session?: string };
export type TelegramChat = { id: string; title: string; username: string; kind: string };
export type DiagnosticEntry = { timestamp?: string; level: string; event: string; request_id?: string; method?: string; path?: string; status_code?: number; duration_ms?: number; error_type?: string };
export type ContentUpdateStatus = { enabled: boolean; version: string | null; source: string };
export type StockSourceRow = {
  ticker: string;
  company: string;
  company_ar?: string;
  channel: string;
  occurrences: number;
  details: Array<Record<string, string>>;
  notes?: string;
};

export type StockSummaryRow = {
  ticker: string;
  company: string;
  company_ar?: string;
  occurrences: number;
  by_chat: Record<string, number>;
  data_samples: Array<{ channel: string; data: Record<string, string>; context?: string }>;
};

export type SelectedAnalysisResult = {
  messages_collected: number;
  messages_in_window: number;
  messages_analyzed: number;
  messages_reanalyzed: number;
  messages_already_saved: number;
  window_start: string;
  lookback_days: number;
  report: {
    id: number;
    markdown_path: string;
    html_path: string;
    pdf_path: string;
    original_ai_response_text_path: string;
    original_ai_response_pdf_path: string;
  };
  trace: {
    directory: string;
    text_path: string;
    images_path: string;
    message_count: number;
    image_count: number;
  };
  channel_results: Array<{ channel: string; status: string; messages: number; recommendations: number; stock_codes: number }>;
  stock_code_summary: StockSummaryRow[];
  stock_code_details: StockSourceRow[];
  not_stock_related: string[];
};

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly requestId?: string) { super(message); this.name = "ApiError"; }
}

async function responseError(path: string, response: Response): Promise<ApiError> {
  const requestId = response.headers.get("X-EGX-Request-ID") || undefined;
  let detail = response.statusText || "Unexpected server response";
  try {
    const payload = await response.json() as { detail?: unknown };
    if (typeof payload.detail === "string") detail = payload.detail;
  } catch {
    const text = await response.text();
    if (text) detail = text;
  }
  const reference = requestId ? ` Reference: ${requestId}.` : "";
  return new ApiError(`${path} returned ${response.status}: ${detail}.${reference}`, response.status, requestId);
}

export class ApiClient {
  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${baseUrl}${path}`, { ...init, headers: { "Content-Type": "application/json", ...init.headers } });
    } catch (error) {
      const reason = error instanceof Error && error.message ? ` (${error.message})` : "";
      throw new Error(`Could not reach the local engine while calling ${path}.${reason} It may still be starting.`);
    }
    if (!response.ok) throw await responseError(path, response);
    return response.json() as Promise<T>;
  }
  channels() { return this.request<Channel[]>("/channels"); }
  settings() { return this.request<SettingsStatus>("/settings"); }
  models() { return this.request<string[]>("/models"); }
  saveSettings(values: SettingsInput) { return this.request<SettingsStatus>("/settings", { method: "PUT", body: JSON.stringify(values) }); }
  requestTelegramCode(phone: string) { return this.request<{ status: string }>("/telegram/request-code", { method: "POST", body: JSON.stringify({ phone }) }); }
  verifyTelegramCode(code: string, password?: string) { return this.request<{ authorized: boolean }>("/telegram/verify-code", { method: "POST", body: JSON.stringify({ code, password }) }); }
  telegramChats() { return this.request<TelegramChat[]>("/telegram/chats"); }
  diagnostics() { return this.request<{ path: string; entries: DiagnosticEntry[] }>("/diagnostics/recent"); }
  contentUpdates() { return this.request<ContentUpdateStatus>("/content-updates"); }
  checkContentUpdates() { return this.request<{ updated: boolean; version: string }>("/content-updates/check", { method: "POST" }); }
  selectTelegramChat(chat: TelegramChat) { return this.request<Channel>("/telegram/chats/select", { method: "POST", body: JSON.stringify(chat) }); }
  runCollection() { return this.request<{ messages_collected: number }>("/collection/run", { method: "POST" }); }
  analyzeSelected(channel_ids: number[], lookback_days: number) { return this.request<SelectedAnalysisResult>("/collection/analyze-selected", { method: "POST", body: JSON.stringify({ channel_ids, analyze: true, lookback_days }) }); }
  addChannel(handle: string, title?: string) { return this.request<Channel>("/channels", { method: "POST", body: JSON.stringify({ handle, title }) }); }
  setChannelActive(id: number, active: boolean) { return this.request<Channel>(`/channels/${id}`, { method: "PATCH", body: JSON.stringify({ active }) }); }
  consensus() { return this.request<Consensus[]>("/analytics/consensus"); }
  recommendations() { return this.request<Array<Record<string, unknown>>>("/recommendations"); }
  reports() { return this.request<Array<Record<string, unknown>>>("/reports"); }
  generateReport(report_mode: "calendar" | "session") { return this.request<Record<string, unknown>>("/reports/daily", { method: "POST", body: JSON.stringify({ report_mode }) }); }
  search(query: string) { return this.request<Array<Record<string, unknown>>>("/search", { method: "POST", body: JSON.stringify({ query }) }); }
}
