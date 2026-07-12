const baseUrl = "http://127.0.0.1:8000";

export type Channel = { id: number; handle: string; title?: string; active: boolean; analyst_score?: number };
export type Consensus = { company: string; sentiment: string; confidence: number; buy_count: number; sell_count: number; hold_count: number };
export type SettingsStatus = { openai_configured: boolean; telegram_configured: boolean; telegram_authorized: boolean; openai_model: string; telegram_session: string };
export type SettingsInput = { openai_api_key?: string; openai_model?: string; telegram_api_id?: number; telegram_api_hash?: string; telegram_session?: string };
export type TelegramChat = { id: string; title: string; username: string; kind: string };
export type DiagnosticEntry = { timestamp?: string; level: string; event: string; request_id?: string; method?: string; path?: string; status_code?: number; duration_ms?: number; error_type?: string };

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
  selectTelegramChat(chat: TelegramChat) { return this.request<Channel>("/telegram/chats/select", { method: "POST", body: JSON.stringify(chat) }); }
  runCollection() { return this.request<{ messages_collected: number }>("/collection/run", { method: "POST" }); }
  analyzeSelected(channel_ids: number[]) { return this.request<{ messages_collected: number }>("/collection/analyze-selected", { method: "POST", body: JSON.stringify({ channel_ids, analyze: true }) }); }
  addChannel(handle: string, title?: string) { return this.request<Channel>("/channels", { method: "POST", body: JSON.stringify({ handle, title }) }); }
  setChannelActive(id: number, active: boolean) { return this.request<Channel>(`/channels/${id}`, { method: "PATCH", body: JSON.stringify({ active }) }); }
  consensus() { return this.request<Consensus[]>("/analytics/consensus"); }
  recommendations() { return this.request<Array<Record<string, unknown>>>("/recommendations"); }
  reports() { return this.request<Array<Record<string, unknown>>>("/reports"); }
  generateReport(report_mode: "calendar" | "session") { return this.request<Record<string, unknown>>("/reports/daily", { method: "POST", body: JSON.stringify({ report_mode }) }); }
  search(query: string) { return this.request<Array<Record<string, unknown>>>("/search", { method: "POST", body: JSON.stringify({ query }) }); }
}
