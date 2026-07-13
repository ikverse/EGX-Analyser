import { FormEvent, isValidElement, useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getVersion } from "@tauri-apps/api/app";
import { check } from "@tauri-apps/plugin-updater";

import { AiProvider, ApiClient, Channel, Consensus, ContentUpdateStatus, DiagnosticEntry, EngineUpdateStatus, SelectedAnalysisResult, SettingsInput, SettingsStatus, TelegramChat } from "./api";

type Page = "Dashboard" | "Channels" | "Recommendations" | "Reports" | "Search" | "Settings";
type Toast = { kind: "success" | "error" | "warning"; text: string } | null;
type UpdateCandidate = {
  version: string;
  body?: string | null;
  downloadAndInstall: (onEvent: (event: { event: string; data: { contentLength?: number; chunkLength?: number } }) => void) => Promise<void>;
};

const pages: Page[] = ["Dashboard", "Channels", "Recommendations", "Reports", "Search", "Settings"];

export default function App() {
  const [connected, setConnected] = useState(false);
  const [page, setPage] = useState<Page>("Dashboard");
  const [channels, setChannels] = useState<Channel[]>([]);
  const [consensus, setConsensus] = useState<Consensus[]>([]);
  const [rows, setRows] = useState<Array<Record<string, unknown>>>([]);
  const [settings, setSettings] = useState<SettingsStatus | null>(null);
  const [error, setError] = useState("");
  const [engineStarting, setEngineStarting] = useState(true);
  const [toast, setToast] = useState<Toast>(null);
  const [availableUpdate, setAvailableUpdate] = useState<UpdateCandidate | null>(null);
  const [checkingUpdate, setCheckingUpdate] = useState(false);
  const [downloadingUpdate, setDownloadingUpdate] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState<number | null>(null);
  const api = useMemo(() => new ApiClient(), []);

  const notify = (kind: NonNullable<Toast>["kind"], text: string) => setToast({ kind, text });
  const refresh = async (showFailure = true): Promise<boolean> => {
    try {
      const [nextChannels, nextConsensus, nextSettings] = await Promise.all([api.channels(), api.consensus(), api.settings()]);
      setChannels(nextChannels);
      setConsensus(nextConsensus);
      setSettings(nextSettings);
      setConnected(true);
      setEngineStarting(false);
      setError("");
      return true;
    } catch (reason) {
      setConnected(false);
      if (showFailure) setError(displayError(reason));
      return false;
    }
  };

  const checkForUpdates = async (manual: boolean) => {
    setCheckingUpdate(true);
    try {
      const update = await check();
      if (update) {
        setAvailableUpdate(update as UpdateCandidate);
        notify("success", `Version ${update.version} is ready to install.`);
      } else if (manual) {
        notify("success", "You already have the latest version.");
      }
    } catch (reason) {
      notify(manual ? "error" : "warning", updateErrorMessage(reason));
    } finally {
      setCheckingUpdate(false);
    }
  };

  const installUpdate = async () => {
    if (!availableUpdate) return;
    setDownloadingUpdate(true);
    setDownloadProgress(0);
    let downloaded = 0;
    let contentLength = 0;
    try {
      await availableUpdate.downloadAndInstall((event) => {
        if (event.event === "Started") contentLength = event.data.contentLength ?? 0;
        if (event.event === "Progress") {
          downloaded += event.data.chunkLength ?? 0;
          setDownloadProgress(contentLength ? Math.min(100, Math.round((downloaded / contentLength) * 100)) : null);
        }
        if (event.event === "Finished") setDownloadProgress(100);
      });
      notify("success", "Update installed. Restarting EGX Intelligence now.");
      await invoke("restart_app");
    } catch (reason) {
      setDownloadingUpdate(false);
      setDownloadProgress(null);
      notify("error", `Update could not be installed: ${displayError(reason)}. Use the installer from GitHub Releases if this continues.`);
    }
  };

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 5000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: number | undefined;
    const waitForEngine = async () => {
      const ready = await refresh(false);
      if (!ready && !cancelled) retryTimer = window.setTimeout(waitForEngine, 500);
    };
    void waitForEngine();
    return () => { cancelled = true; if (retryTimer) window.clearTimeout(retryTimer); };
  }, [api]);
  useEffect(() => {
    if (!connected) return;
    const timer = window.setTimeout(() => void checkForUpdates(false), 1200);
    return () => window.clearTimeout(timer);
  }, [connected]);
  useEffect(() => {
    if (connected && page === "Recommendations") void api.recommendations().then(setRows);
    if (connected && page === "Reports") void api.reports().then(setRows);
  }, [api, connected, page]);

  if (!connected) {
    return <main className="login"><h1>EGX Intelligence</h1><p>{engineStarting ? "Starting your local intelligence workspace…" : error || "Restarting the local intelligence workspace…"}</p><span>Waiting for the local engine to become ready.</span></main>;
  }

  return <>
    <main className="shell">
      <aside>
        <h1>EGX Intelligence</h1>
        {pages.map((item) => <button className={page === item ? "active" : ""} onClick={() => setPage(item)} key={item}>{item}</button>)}
      </aside>
      <section>
        <header><div><strong>{page}</strong><span className="online">● Local engine online</span></div><button onClick={() => void refresh()}>Refresh</button></header>
        {availableUpdate && <UpdateBanner update={availableUpdate} downloading={downloadingUpdate} progress={downloadProgress} onInstall={() => void installUpdate()} onDismiss={() => setAvailableUpdate(null)} />}
        {page === "Dashboard" && <Dashboard channels={channels} consensus={consensus} api={api} refresh={refresh} notify={notify} />}
        {page === "Channels" && <Channels channels={channels} api={api} refresh={refresh} notify={notify} />}
        {page === "Recommendations" && <Table rows={rows} />}
        {page === "Reports" && <Reports api={api} rows={rows} setRows={setRows} notify={notify} />}
        {page === "Search" && <Search api={api} onResult={setRows} notify={notify} />}
        {page === "Settings" && <CloudSettings api={api} status={settings} onSaved={refresh} notify={notify} checkingUpdate={checkingUpdate} onCheckForUpdates={() => void checkForUpdates(true)} />}
      </section>
    </main>
    {toast && <div className={`toast ${toast.kind}`} role="status"><strong>{toast.kind}</strong><span>{toast.text}</span><button onClick={() => setToast(null)} aria-label="Dismiss">×</button></div>}
  </>;
}

function Dashboard({ channels, consensus, api, refresh, notify }: { channels: Channel[]; consensus: Consensus[]; api: ApiClient; refresh: () => Promise<boolean>; notify: Notify }) {
  return <><div className="metrics"><Metric value={consensus.length} label="Stocks discussed" /><Metric value={consensus.filter((item) => item.sentiment === "BUY").length} label="Buy consensus" /><Metric value={channels.filter((item) => item.active).length} label="Active channels" /></div><button onClick={() => void api.runCollection().then(refresh).then(() => notify("success", "Telegram check completed.")).catch((reason) => notify("error", displayError(reason)))}>Check Telegram now</button><Table rows={consensus as unknown as Array<Record<string, unknown>>} /></>;
}

function Reports({ api, rows, setRows, notify }: { api: ApiClient; rows: Array<Record<string, unknown>>; setRows: (rows: Array<Record<string, unknown>>) => void; notify: Notify }) {
  const [mode, setMode] = useState<"calendar" | "session">("calendar");
  return <><label>Report period<select value={mode} onChange={(event) => setMode(event.target.value as "calendar" | "session")}><option value="calendar">Cairo calendar day</option><option value="session">EGX trading session</option></select></label><button onClick={() => void api.generateReport(mode).then(() => api.reports()).then(setRows).then(() => notify("success", "Bilingual consolidated report created.")).catch((reason) => notify("error", displayError(reason)))}>Generate consolidated report</button><Table rows={rows} /></>;
}

type Notify = (kind: "success" | "error" | "warning", text: string) => void;

function Channels({ channels, api, refresh, notify }: { channels: Channel[]; api: ApiClient; refresh: () => Promise<boolean>; notify: Notify }) {
  const [handle, setHandle] = useState("");
  const [chats, setChats] = useState<TelegramChat[]>(() => { localStorage.removeItem("egx.telegramChats"); try { return JSON.parse(sessionStorage.getItem("egx.telegramChats") || "[]") as TelegramChat[]; } catch { return []; } });
  const [selectedHandles, setSelectedHandles] = useState<string[]>(() => { try { return JSON.parse(sessionStorage.getItem("egx.selectedTelegramChats") || "[]") as string[]; } catch { return []; } });
  const [loading, setLoading] = useState(false);
  const [lastAnalysis, setLastAnalysis] = useState<SelectedAnalysisResult | null>(null);
  const submit = (event: FormEvent) => { event.preventDefault(); void api.addChannel(handle).then(() => { setHandle(""); return refresh(); }).then(() => notify("success", "Channel added for analysis.")).catch((reason) => notify("error", displayError(reason))); };
  const loadChats = () => { setLoading(true); void api.telegramChats().then((items) => { setChats(items); sessionStorage.setItem("egx.telegramChats", JSON.stringify(items)); notify(items.length ? "success" : "warning", items.length ? `${items.length} Telegram chats loaded for this session.` : "No chats were found."); }).catch((reason) => notify("error", displayError(reason))).finally(() => setLoading(false)); };
  const updateSelectedHandles = (handles: string[]) => { setSelectedHandles(handles); sessionStorage.setItem("egx.selectedTelegramChats", JSON.stringify(handles)); };
  const addChat = (chat: TelegramChat) => { setLoading(true); void api.selectTelegramChat(chat).then((channel) => { updateSelectedHandles([...new Set([...selectedHandles, channel.handle])]); return refresh(); }).then(() => notify("success", `${chat.title} is selected for this session.`)).catch((reason) => notify("error", displayError(reason))).finally(() => setLoading(false)); };
  const removeChat = (handle: string) => { updateSelectedHandles(selectedHandles.filter((item) => item !== handle)); notify("success", "Chat removed from this session."); };
  const selected = new Set(selectedHandles);
  const selectedChannels = channels.filter((channel) => selected.has(channel.handle));
  const analyze = () => { const ids = selectedChannels.map((channel) => channel.id); if (!ids.length) return notify("warning", "Select at least one chat first."); setLoading(true); void api.analyzeSelected(ids).then((result) => { setLastAnalysis(result); return refresh().then(() => notify(result.not_stock_related.length ? "warning" : "success", `${result.messages_collected} messages analyzed and report created.${result.not_stock_related.length ? ` No stock-related context: ${result.not_stock_related.join(", ")}.` : ""}`)); }).catch((reason) => notify("error", displayError(reason))).finally(() => setLoading(false)); };
  const selectedRows = selectedChannels.map((channel) => ({ ...channel, selection: <button className="secondary" onClick={() => removeChat(channel.handle)}>Remove</button> }));
  const chatRows = chats.map((chat) => ({ chat: `${chat.title}${chat.username ? ` (@${chat.username})` : ""}`, type: chat.kind, selection: <button disabled={loading} onClick={() => selected.has(chat.id) ? removeChat(chat.id) : addChat(chat)}>{selected.has(chat.id) ? "Remove" : "Select"}</button> }));
  return <>
    <form className="inline" onSubmit={submit}><input value={handle} onChange={(event) => setHandle(event.target.value)} placeholder="Telegram username, without @" required /><button disabled={loading}>Add channel</button></form>
    <button onClick={loadChats} disabled={loading}>{loading ? "Loading chats..." : "Load my Telegram chats"}</button>
    {chats.length > 0 && <Table rows={chatRows} />}
    <h3>Selected chats ({selectedChannels.length})</h3>
    <button onClick={analyze} disabled={loading}>{loading ? "Analyzing selected chats..." : "Analyze selected chats"}</button>
    <Table rows={selectedRows} />
    {lastAnalysis && <><h3>Latest analysis report</h3><p>Report created: {lastAnalysis.report.pdf_path}</p><Table rows={lastAnalysis.channel_results} /></>}
  </>;
}

function Search({ api, onResult, notify }: { api: ApiClient; onResult: (rows: Array<Record<string, unknown>>) => void; notify: Notify }) {
  const [query, setQuery] = useState("");
  return <form className="inline" onSubmit={(event) => { event.preventDefault(); void api.search(query).then(onResult).catch((reason) => notify("error", displayError(reason))); }}><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Ask about CIB, TMG, or market changes" required /><button>Search</button></form>;
}

function ModelSelector({ api, configured, selected, onChange, notify }: { api: ApiClient; configured: boolean; selected: string; onChange: (value: string) => void; notify: Notify }) {
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const load = async (announce: boolean) => {
    if (!configured) { if (announce) notify("warning", "Save an API key for the selected provider first."); return; }
    setLoading(true);
    try { const loaded = await api.models(); setModels(loaded); if (announce) notify(loaded.length ? "success" : "warning", loaded.length ? `${loaded.length} available models loaded.` : "No compatible analysis models are available to this API key."); }
    catch (reason) { notify("error", `Could not load models: ${displayError(reason)}`); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(false); }, [api, configured]);
  return <label>Analysis model<div className="model-row"><select value={selected} onChange={(event) => onChange(event.target.value)}><option value={selected}>{selected || "Choose a model"}</option>{models.filter((model) => model !== selected).map((model) => <option key={model} value={model}>{model}</option>)}</select><button type="button" onClick={() => void load(true)} disabled={!configured || loading}>{loading ? "Loading…" : "Load available models"}</button></div></label>;
}

function CloudSettings({ api, status, onSaved, notify, checkingUpdate, onCheckForUpdates }: { api: ApiClient; status: SettingsStatus | null; onSaved: () => Promise<boolean>; notify: Notify; checkingUpdate: boolean; onCheckForUpdates: () => void }) {
  const [values, setValues] = useState<SettingsInput>({ ai_provider: status?.ai_provider || "qwen", openai_model: status?.openai_model || "qwen3-vl-plus" });
  const [editingProviderKey, setEditingProviderKey] = useState(false);
  const [editingTelegram, setEditingTelegram] = useState(false);
  const [phone, setPhone] = useState(""); const [code, setCode] = useState(""); const [password, setPassword] = useState(""); const [codeSent, setCodeSent] = useState(false);
  const [diagnostics, setDiagnostics] = useState<DiagnosticEntry[]>([]); const [loadingDiagnostics, setLoadingDiagnostics] = useState(false);
  const [contentStatus, setContentStatus] = useState<ContentUpdateStatus | null>(null); const [checkingContent, setCheckingContent] = useState(false);
  const [engineStatus, setEngineStatus] = useState<EngineUpdateStatus | null>(null); const [checkingEngine, setCheckingEngine] = useState(false);
  const [appVersion, setAppVersion] = useState("");
  const provider = values.ai_provider || status?.ai_provider || "qwen";
  const providerDetails: Record<AiProvider, { label: string; placeholder: string; key: "qwen_api_key" | "openrouter_api_key" | "huggingface_api_key" | "openai_api_key" }> = {
    qwen: { label: "Qwen Cloud", placeholder: "sk-...", key: "qwen_api_key" },
    openrouter: { label: "OpenRouter", placeholder: "sk-or-...", key: "openrouter_api_key" },
    huggingface: { label: "Hugging Face", placeholder: "hf_...", key: "huggingface_api_key" },
    openai: { label: "OpenAI", placeholder: "sk-...", key: "openai_api_key" },
  };
  const currentProvider = providerDetails[provider];
  useEffect(() => { void getVersion().then(setAppVersion).catch(() => setAppVersion("Unknown")); }, []);
  useEffect(() => { void api.contentUpdates().then(setContentStatus).catch(() => setContentStatus(null)); }, [api]);
  useEffect(() => { void api.engineUpdates().then(setEngineStatus).catch(() => setEngineStatus(null)); }, [api]);
  useEffect(() => { if (status) setValues((current) => ({ ...current, ai_provider: status.ai_provider, openai_model: status.openai_model })); }, [status]);
  const save = (event: FormEvent) => {
    event.preventDefault();
    void api.saveSettings(values).then(onSaved).then(() => {
      setValues((current) => ({ ai_provider: current.ai_provider, openai_model: current.openai_model }));
      setEditingProviderKey(false); setEditingTelegram(false); notify("success", "Settings saved securely on this computer.");
    }).catch((reason) => notify("error", `Could not save settings: ${displayError(reason)}`));
  };
  const chooseProvider = (next: AiProvider) => {
    const defaultModel = next === "qwen" ? "qwen3-vl-plus" : next === "openrouter" ? "openrouter/free" : "";
    setValues((current) => ({ ...current, ai_provider: next, openai_model: defaultModel }));
    setEditingProviderKey(false);
  };
  const replaceKey = () => {
    if (editingProviderKey) setValues((current) => ({ ...current, [currentProvider.key]: undefined }));
    setEditingProviderKey((current) => !current);
  };
  return <div className="settings">
    <form onSubmit={save}>
      <p>Cloud provider keys are encrypted and stored only on this computer. No AI model is downloaded locally.</p>
      <label>AI provider<select value={provider} onChange={(event) => chooseProvider(event.target.value as AiProvider)}><option value="qwen">Qwen Cloud — default for Arabic and charts</option><option value="openrouter">OpenRouter — free models available</option><option value="huggingface">Hugging Face Inference Providers</option><option value="openai">OpenAI</option></select></label>
      <div className="credential-header"><div><strong>{currentProvider.label}</strong><span>{status?.ai_provider === provider && status.ai_configured ? "API key saved" : "API key not configured"}</span></div><button type="button" className="secondary" onClick={replaceKey}>{editingProviderKey ? "Cancel" : status?.ai_provider === provider && status.ai_configured ? "Replace API key" : "Add API key"}</button></div>
      {editingProviderKey && <label>New {currentProvider.label} API key<input type="password" autoComplete="new-password" placeholder={currentProvider.placeholder} value={values[currentProvider.key] || ""} onChange={(event) => setValues((current) => ({ ...current, [currentProvider.key]: event.target.value }))} required /></label>}
      {provider === "qwen" && <label>Qwen Cloud endpoint<input type="url" list="qwen-endpoints" value={values.qwen_base_url || "https://dashscope.aliyuncs.com/compatible-mode/v1"} onChange={(event) => setValues((current) => ({ ...current, qwen_base_url: event.target.value }))} required /><datalist id="qwen-endpoints"><option value="https://dashscope.aliyuncs.com/compatible-mode/v1">China (Beijing)</option><option value="https://dashscope-intl.aliyuncs.com/compatible-mode/v1">Singapore</option><option value="https://dashscope-us.aliyuncs.com/compatible-mode/v1">US (Virginia)</option></datalist><span className="credential-note">The key and endpoint must be from the same Model Studio region and pay-as-you-go billing plan. You can also enter your workspace-dedicated endpoint.</span></label>}
      <ModelSelector api={api} configured={Boolean(status?.ai_provider === provider && status.ai_configured)} selected={values.openai_model || ""} onChange={(openai_model) => setValues((current) => ({ ...current, openai_model }))} notify={notify} />
      <div className="credential-header"><div><strong>Telegram</strong><span>{status?.telegram_configured ? "API credentials saved" : "API credentials not configured"}</span></div><button type="button" className="secondary" onClick={() => { if (editingTelegram) setValues(({ telegram_api_id, telegram_api_hash, ...current }) => current); setEditingTelegram((current) => !current); }}>{editingTelegram ? "Cancel" : status?.telegram_configured ? "Replace Telegram credentials" : "Add Telegram credentials"}</button></div>
      {editingTelegram && <><label>New Telegram API ID<input type="number" placeholder="From my.telegram.org" value={values.telegram_api_id || ""} onChange={(event) => setValues((current) => ({ ...current, telegram_api_id: Number(event.target.value) || undefined }))} required /></label><label>New Telegram API hash<input type="password" autoComplete="new-password" placeholder="API hash" value={values.telegram_api_hash || ""} onChange={(event) => setValues((current) => ({ ...current, telegram_api_hash: event.target.value }))} required /></label><p className="credential-note">Changing Telegram credentials signs this computer out of Telegram. Connect it again below after saving.</p></>}
      <button>Save settings</button>
    </form>
    <article className="app-version"><h3>EGX Intelligence</h3><p>Version {appVersion || "Loading…"}</p></article>
    <article className="content-updates"><h3>Analysis content updates</h3><p>Signed prompt and stock-alias updates install without rebuilding or reinstalling the desktop application.</p><p>{contentStatus?.version ? `Installed content pack: ${contentStatus.version}` : "Using built-in analysis content."}</p><button type="button" disabled={checkingContent || contentStatus?.enabled === false} onClick={() => { setCheckingContent(true); void api.checkContentUpdates().then((result) => { notify("success", result.updated ? `Content pack ${result.version} installed.` : `Content pack ${result.version} is already installed.`); return api.contentUpdates(); }).then(setContentStatus).catch((reason) => notify("error", `Could not update analysis content: ${displayError(reason)}`)).finally(() => setCheckingContent(false)); }}>{checkingContent ? "Checking content…" : "Check analysis content"}</button></article>
    <article className="engine-updates"><h3>Engine quick patches</h3><p>Downloads only a signed local API engine patch. The desktop app restarts only when a patch is ready.</p><p>Running engine: {engineStatus?.version || "Built-in"}</p><button type="button" disabled={checkingEngine} onClick={() => { setCheckingEngine(true); void api.checkEngineUpdates().then(async (result) => { if (!result.updated) { notify("success", `Engine ${result.version} is already installed.`); return; } notify("success", `Engine patch ${result.version} downloaded. Restarting now.`); await invoke("restart_app"); }).catch((reason) => notify("error", `Could not update the engine: ${displayError(reason)}`)).finally(() => setCheckingEngine(false)); }}>{checkingEngine ? "Downloading engine patch…" : "Check engine quick patches"}</button></article>
    <form className="update-settings" onSubmit={(event) => { event.preventDefault(); onCheckForUpdates(); }}><h3>Application updates</h3><p>Checks for a signed EGX Intelligence update and keeps your local data unchanged.</p><button disabled={checkingUpdate}>{checkingUpdate ? "Checking…" : "Check for updates"}</button></form>
    <article className="diagnostics"><h3>Diagnostics</h3><p>Stores local request results and error traces. API keys, codes, and passwords are never logged.</p><button type="button" className="secondary" disabled={loadingDiagnostics} onClick={() => { setLoadingDiagnostics(true); void api.diagnostics().then((result) => { setDiagnostics(result.entries); notify("success", "Recent diagnostics loaded."); }).catch((reason) => notify("error", `Could not load diagnostics: ${displayError(reason)}`)).finally(() => setLoadingDiagnostics(false)); }}>{loadingDiagnostics ? "Loading diagnostics…" : "View recent diagnostics"}</button>{diagnostics.length > 0 && <pre>{diagnostics.map((entry) => `${entry.timestamp || ""} ${entry.level} ${entry.event} ${entry.method || ""} ${entry.path || ""} ${entry.status_code || ""} ${entry.error_type || ""}`).join("\n")}</pre>}</article>
    {!status?.telegram_authorized && <form onSubmit={(event) => { event.preventDefault(); void api.requestTelegramCode(phone).then(() => { setCodeSent(true); notify("success", "Telegram code sent. Enter it below."); }).catch((reason) => notify("error", `Could not send Telegram code: ${displayError(reason)}`)); }}><h3>Connect Telegram</h3><label>Phone number<input value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="+201..." required /></label><button>Send code</button></form>}
    {!status?.telegram_authorized && codeSent && <form onSubmit={(event) => { event.preventDefault(); void api.verifyTelegramCode(code, password || undefined).then(() => onSaved()).then(() => notify("success", "Telegram connected and saved for future launches.")).catch((reason) => notify("error", `Telegram connection failed: ${displayError(reason)}`)); }}><label>Verification code<input value={code} onChange={(event) => setCode(event.target.value)} required /></label><label>Two-step password (only if enabled)<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label><button>Verify code</button></form>}
  </div>;
}

function Settings({ api, status, onSaved, notify, checkingUpdate, onCheckForUpdates }: { api: ApiClient; status: SettingsStatus | null; onSaved: () => Promise<boolean>; notify: Notify; checkingUpdate: boolean; onCheckForUpdates: () => void }) {
  const [values, setValues] = useState<SettingsInput>({ openai_model: status?.openai_model || "gpt-5.5" });
  const [phone, setPhone] = useState(""); const [code, setCode] = useState(""); const [password, setPassword] = useState(""); const [codeSent, setCodeSent] = useState(false);
  const [editingOpenAi, setEditingOpenAi] = useState(false); const [editingTelegram, setEditingTelegram] = useState(false);
  const [diagnostics, setDiagnostics] = useState<DiagnosticEntry[]>([]); const [loadingDiagnostics, setLoadingDiagnostics] = useState(false);
  useEffect(() => { if (status?.openai_model) setValues((current) => ({ ...current, openai_model: status.openai_model })); }, [status?.openai_model]);
  const save = (event: FormEvent) => { event.preventDefault(); void api.saveSettings(values).then(onSaved).then(() => { setValues((current) => ({ openai_model: current.openai_model })); setEditingOpenAi(false); setEditingTelegram(false); notify("success", "Settings saved securely on this computer."); }).catch((reason) => notify("error", `Could not save settings: ${displayError(reason)}`)); };
  return <div className="settings">
    <form onSubmit={save}><p>Credentials are encrypted and stored only on this computer.</p><div className="credential-header"><div><strong>OpenAI</strong><span>{status?.openai_configured ? "API key saved" : "API key not configured"}</span></div><button type="button" className="secondary" onClick={() => { if (editingOpenAi) setValues(({ openai_api_key, ...current }) => current); setEditingOpenAi((current) => !current); }}>{editingOpenAi ? "Cancel" : status?.openai_configured ? "Replace API key" : "Add API key"}</button></div>{editingOpenAi && <label>New OpenAI API key<input type="password" autoComplete="new-password" placeholder="sk-..." value={values.openai_api_key || ""} onChange={(event) => setValues({ ...values, openai_api_key: event.target.value })} required /></label>}<ModelSelector api={api} configured={Boolean(status?.openai_configured)} selected={values.openai_model || ""} onChange={(openai_model) => setValues({ ...values, openai_model })} notify={notify} /><div className="credential-header"><div><strong>Telegram</strong><span>{status?.telegram_configured ? "API credentials saved" : "API credentials not configured"}</span></div><button type="button" className="secondary" onClick={() => { if (editingTelegram) setValues(({ telegram_api_id, telegram_api_hash, ...current }) => current); setEditingTelegram((current) => !current); }}>{editingTelegram ? "Cancel" : status?.telegram_configured ? "Replace Telegram credentials" : "Add Telegram credentials"}</button></div>{editingTelegram && <><label>New Telegram API ID<input type="number" placeholder="From my.telegram.org" value={values.telegram_api_id || ""} onChange={(event) => setValues({ ...values, telegram_api_id: Number(event.target.value) || undefined })} required /></label><label>New Telegram API hash<input type="password" autoComplete="new-password" placeholder="API hash" value={values.telegram_api_hash || ""} onChange={(event) => setValues({ ...values, telegram_api_hash: event.target.value })} required /></label><p className="credential-note">Changing Telegram credentials signs this computer out of Telegram. Connect it again below after saving.</p></>}<button>Save settings</button></form>
    <form className="update-settings" onSubmit={(event) => { event.preventDefault(); onCheckForUpdates(); }}><h3>Application updates</h3><p>Checks for a signed EGX Intelligence update and keeps your local data unchanged.</p><button disabled={checkingUpdate}>{checkingUpdate ? "Checking…" : "Check for updates"}</button></form>
    <article className="diagnostics"><h3>Diagnostics</h3><p>Stores local request results and error traces. API keys, codes, and passwords are never logged.</p><button type="button" className="secondary" disabled={loadingDiagnostics} onClick={() => { setLoadingDiagnostics(true); void api.diagnostics().then((result) => { setDiagnostics(result.entries); notify("success", "Recent diagnostics loaded."); }).catch((reason) => notify("error", `Could not load diagnostics: ${displayError(reason)}`)).finally(() => setLoadingDiagnostics(false)); }}>{loadingDiagnostics ? "Loading diagnostics…" : "View recent diagnostics"}</button>{diagnostics.length > 0 && <pre>{diagnostics.map((entry) => `${entry.timestamp || ""} ${entry.level} ${entry.event} ${entry.method || ""} ${entry.path || ""} ${entry.status_code || ""} ${entry.error_type || ""}`).join("\n")}</pre>}</article>
    {!status?.telegram_authorized && <form onSubmit={(event) => { event.preventDefault(); void api.requestTelegramCode(phone).then(() => { setCodeSent(true); notify("success", "Telegram code sent. Enter it below."); }).catch((reason) => notify("error", `Could not send Telegram code: ${displayError(reason)}`)); }}><h3>Connect Telegram</h3><label>Phone number<input value={phone} onChange={(event) => setPhone(event.target.value)} placeholder="+201..." required /></label><button>Send code</button></form>}
    {!status?.telegram_authorized && codeSent && <form onSubmit={(event) => { event.preventDefault(); void api.verifyTelegramCode(code, password || undefined).then(() => onSaved()).then(() => notify("success", "Telegram connected and saved for future launches.")).catch((reason) => notify("error", `Telegram connection failed: ${displayError(reason)}`)); }}><label>Verification code<input value={code} onChange={(event) => setCode(event.target.value)} required /></label><label>Two-step password (only if enabled)<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label><button>Verify code</button></form>}
  </div>;
}

function UpdateBanner({ update, downloading, progress, onInstall, onDismiss }: { update: UpdateCandidate; downloading: boolean; progress: number | null; onInstall: () => void; onDismiss: () => void }) {
  return <article className="update-banner"><div><strong>Update available: {update.version}</strong><p>{update.body || "A newer, signed version of EGX Intelligence is ready."}</p>{downloading && <p>{progress === null ? "Downloading update…" : `Downloading update: ${progress}%`}</p>}</div><div className="update-actions"><button onClick={onInstall} disabled={downloading}>{downloading ? "Installing…" : "Download and install"}</button><button className="secondary" onClick={onDismiss} disabled={downloading}>Later</button></div></article>;
}

function Metric({ value, label }: { value: number; label: string }) { return <article><b>{value}</b><span>{label}</span></article>; }
function Table({ rows }: { rows: Array<Record<string, unknown>> }) { if (!rows.length) return <p className="empty">No records yet.</p>; const headers = Object.keys(rows[0]); return <div className="table"><table><thead><tr>{headers.map((header) => <th key={header}>{header.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{headers.map((header) => <td key={header}>{isValidElement(row[header]) ? row[header] : String(row[header] ?? "—")}</td>)}</tr>)}</tbody></table></div>; }
function displayError(error: unknown): string { const text = error instanceof Error ? error.message : "Request failed"; return text.length > 220 ? `${text.slice(0, 217)}…` : text; }
function updateErrorMessage(error: unknown): string { const detail = displayError(error); return /endpoint|updater|config/i.test(detail) ? "Updates are not configured yet. Run the one-time updater setup before publishing the first release." : `Could not check for updates: ${detail}`; }
