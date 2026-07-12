const baseUrl = "http://127.0.0.1:8000";

export type Channel = { id: number; handle: string; title?: string; active: boolean; analyst_score?: number };
export type Consensus = { company: string; sentiment: string; confidence: number; buy_count: number; sell_count: number; hold_count: number };
export type SettingsStatus = { openai_configured: boolean; telegram_configured: boolean; telegram_authorized: boolean; openai_model: string; telegram_session: string };
export type SettingsInput = { openai_api_key?: string; openai_model?: string; telegram_api_id?: number; telegram_api_hash?: string; telegram_session?: string };
export type TelegramChat = { id: string; title: string; username: string; kind: string };

export class ApiClient {
  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${baseUrl}${path}`, { ...init, headers: { "Content-Type": "application/json", ...init.headers } });
    if (!response.ok) throw new Error(await response.text());
    return response.json() as Promise<T>;
  }
  channels() { return this.request<Channel[]>("/channels"); }
  settings() { return this.request<SettingsStatus>("/settings"); }
  models() { return this.request<string[]>("/models"); }
  saveSettings(values: SettingsInput) { return this.request<SettingsStatus>("/settings", { method: "PUT", body: JSON.stringify(values) }); }
  requestTelegramCode(phone: string) { return this.request<{ status: string }>("/telegram/request-code", { method: "POST", body: JSON.stringify({ phone }) }); }
  verifyTelegramCode(code: string, password?: string) { return this.request<{ authorized: boolean }>("/telegram/verify-code", { method: "POST", body: JSON.stringify({ code, password }) }); }
  telegramChats() { return this.request<TelegramChat[]>("/telegram/chats"); }
  runCollection() { return this.request<{ messages_collected: number }>("/collection/run", { method: "POST" }); }
  addChannel(handle: string, title?: string) { return this.request<Channel>("/channels", { method: "POST", body: JSON.stringify({ handle, title }) }); }
  setChannelActive(id: number, active: boolean) { return this.request<Channel>(`/channels/${id}`, { method: "PATCH", body: JSON.stringify({ active }) }); }
  consensus() { return this.request<Consensus[]>("/analytics/consensus"); }
  recommendations() { return this.request<Array<Record<string, unknown>>>("/recommendations"); }
  reports() { return this.request<Array<Record<string, unknown>>>("/reports"); }
  generateReport() { return this.request<Record<string, unknown>>("/reports/daily", { method: "POST" }); }
  search(query: string) { return this.request<Array<Record<string, unknown>>>("/search", { method: "POST", body: JSON.stringify({ query }) }); }
}
