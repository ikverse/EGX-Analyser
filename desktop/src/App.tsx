import { FormEvent, isValidElement, useCallback, useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getVersion } from "@tauri-apps/api/app";
import { check } from "@tauri-apps/plugin-updater";

import {
  AiProvider, ApiClient, Channel, Consensus, ContentUpdateStatus,
  DiagnosticEntry, SelectedAnalysisResult, SettingsInput, SettingsStatus, TelegramChat,
} from "./api";

type Page = "Dashboard" | "Channels" | "Recommendations" | "Reports" | "Search" | "Settings";
type Toast = { kind: "success" | "warning"; text: string } | null;
type UpdateCandidate = {
  version: string;
  body?: string | null;
  downloadAndInstall: (onEvent: (event: { event: string; data: { contentLength?: number; chunkLength?: number } }) => void) => Promise<void>;
};

const pages: Page[] = ["Dashboard", "Channels", "Recommendations", "Reports", "Search", "Settings"];

// ── Error Modal ───────────────────────────────────────────────────────────────

function ErrorModal({ message, onClose }: { message: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    void navigator.clipboard.writeText(message).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    });
  };
  return (
    <div className="error-modal-backdrop" role="dialog" aria-modal="true" aria-label="Error">
      <div className="error-modal-card">
        <h2 className="error-modal-title">Error</h2>
        <pre className="error-modal-body">{message}</pre>
        <div className="error-modal-actions">
          <button type="button" className="secondary" onClick={copy}>
            {copied ? "Copied" : "Copy Message"}
          </button>
          <button type="button" onClick={onClose}>OK</button>
        </div>
      </div>
    </div>
  );
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const [connected, setConnected] = useState(false);
  const [page, setPage] = useState<Page>("Dashboard");
  const [channels, setChannels] = useState<Channel[]>([]);
  const [consensus, setConsensus] = useState<Consensus[]>([]);
  const [rows, setRows] = useState<Array<Record<string, unknown>>>([]);
  const [settings, setSettings] = useState<SettingsStatus | null>(null);
  const [engineStarting, setEngineStarting] = useState(true);
  const [toast, setToast] = useState<Toast>(null);
  const [errorModal, setErrorModal] = useState<string | null>(null);
  const [availableUpdate, setAvailableUpdate] = useState<UpdateCandidate | null>(null);
  const [checkingUpdate, setCheckingUpdate] = useState(false);
  const [downloadingUpdate, setDownloadingUpdate] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState<number | null>(null);
  const api = useMemo(() => new ApiClient(), []);

  const notify = (kind: "success" | "warning", text: string) => setToast({ kind, text });

  const showError = useCallback((fullText: string) => {
    setErrorModal(fullText);
    const short = fullText.length > 120 ? `${fullText.slice(0, 117)}…` : fullText;
    setToast({ kind: "warning", text: short });
  }, []);

  const refresh = async (showFailure = true): Promise<boolean> => {
    try {
      const [nextChannels, nextConsensus, nextSettings] = await Promise.all([
        api.channels(), api.consensus(), api.settings(),
      ]);
      setChannels(nextChannels);
      setConsensus(nextConsensus);
      setSettings(nextSettings);
      setConnected(true);
      setEngineStarting(false);
      return true;
    } catch (reason) {
      setConnected(false);
      if (showFailure) showError(fullError(reason));
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
      const msg = updateErrorMessage(reason);
      if (manual) showError(msg); else notify("warning", msg);
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
      showError(`Update could not be installed: ${fullError(reason)}. Use the installer from GitHub Releases if this continues.`);
    }
  };

  // Auto-dismiss toasts; error modal stays until OK
  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 5000);
    return () => window.clearTimeout(timer);
  }, [toast]);

  // Poll until engine ready
  useEffect(() => {
    let cancelled = false;
    let retryTimer: number | undefined;
    const waitForEngine = async () => {
      const ready = await refresh(false);
      if (!ready && !cancelled) retryTimer = window.setTimeout(waitForEngine, 500);
    };
    void waitForEngine();
    return () => {
      cancelled = true;
      if (retryTimer) window.clearTimeout(retryTimer);
    };
  }, [api]);

  // Check for updates once connected
  useEffect(() => {
    if (!connected) return;
    const timer = window.setTimeout(() => void checkForUpdates(false), 1200);
    return () => window.clearTimeout(timer);
  }, [connected]);

  // Refresh page data on navigation
  useEffect(() => {
    if (connected && page === "Recommendations") void api.recommendations().then(setRows);
    if (connected && page === "Reports") void api.reports().then(setRows);
  }, [api, connected, page]);

  if (!connected) {
    return (
      <main className="login">
        <h1>EGX Intelligence</h1>
        <p>{engineStarting ? "Starting your local intelligence workspace…" : "Restarting the local intelligence workspace…"}</p>
        <span>Waiting for the local engine to become ready.</span>
      </main>
    );
  }

  return (
    <>
      <main className="shell">
        <aside>
          <h1>EGX Intelligence</h1>
          {pages.map((item) => (
            <button className={page === item ? "active" : ""} onClick={() => setPage(item)} key={item}>
              {item}
            </button>
          ))}
        </aside>
        <section>
          <header>
            <div>
              <strong>{page}</strong>
              <span className="online">{"●"} Local engine online</span>
            </div>
            <button onClick={() => void refresh()}>Refresh</button>
          </header>
          {availableUpdate && (
            <UpdateBanner
              update={availableUpdate}
              downloading={downloadingUpdate}
              progress={downloadProgress}
              onInstall={() => void installUpdate()}
              onDismiss={() => setAvailableUpdate(null)}
            />
          )}
          {page === "Dashboard" && <Dashboard channels={channels} consensus={consensus} api={api} refresh={refresh} notify={notify} showError={showError} />}
          {page === "Channels" && <Channels channels={channels} api={api} refresh={refresh} notify={notify} showError={showError} />}
          {page === "Recommendations" && <Recommendations rows={rows} />}
          {page === "Reports" && <Reports api={api} rows={rows} setRows={setRows} notify={notify} showError={showError} />}
          {page === "Search" && <Search api={api} onResult={setRows} notify={notify} showError={showError} />}
          {page === "Settings" && (
            <CloudSettings
              api={api}
              status={settings}
              onSaved={refresh}
              notify={notify}
              showError={showError}
              checkingUpdate={checkingUpdate}
              onCheckForUpdates={() => void checkForUpdates(true)}
            />
          )}
        </section>
      </main>

      {/* Blocking error modal — only dismissed by pressing OK */}
      {errorModal && <ErrorModal message={errorModal} onClose={() => setErrorModal(null)} />}

      {/* Non-blocking toasts for success and warnings */}
      {toast && (
        <div className={`toast ${toast.kind}`} role="status">
          <strong>{toast.kind}</strong>
          <span>{toast.text}</span>
          <button onClick={() => setToast(null)} aria-label="Dismiss">{"×"}</button>
        </div>
      )}
    </>
  );
}

// ── Shared types ──────────────────────────────────────────────────────────────

type Notify = (kind: "success" | "warning", text: string) => void;
type ShowError = (message: string) => void;

// ── Dashboard ─────────────────────────────────────────────────────────────────

function Dashboard({ channels, consensus, api, refresh, notify, showError }: {
  channels: Channel[]; consensus: Consensus[]; api: ApiClient;
  refresh: () => Promise<boolean>; notify: Notify; showError: ShowError;
}) {
  const [running, setRunning] = useState(false);
  const run = () => {
    setRunning(true);
    void api.runCollection()
      .then(() => refresh())
      .then(() => notify("success", "Telegram check completed."))
      .catch((reason) => showError(fullError(reason)))
      .finally(() => setRunning(false));
  };
  return (
    <>
      <div className="metrics">
        <Metric value={consensus.length} label="Stocks discussed" />
        <Metric value={consensus.filter((item) => item.sentiment === "BUY").length} label="Buy consensus" />
        <Metric value={channels.filter((item) => item.active).length} label="Active channels" />
      </div>
      <button onClick={run} disabled={running}>{running ? "Checking Telegram…" : "Check Telegram now"}</button>
      <Table rows={consensus as unknown as Array<Record<string, unknown>>} />
    </>
  );
}

// ── Reports ───────────────────────────────────────────────────────────────────

function Reports({ api, rows, setRows, notify, showError }: {
  api: ApiClient; rows: Array<Record<string, unknown>>;
  setRows: (rows: Array<Record<string, unknown>>) => void;
  notify: Notify; showError: ShowError;
}) {
  const [mode, setMode] = useState<"calendar" | "session">("calendar");
  const [generating, setGenerating] = useState(false);
  const generate = () => {
    setGenerating(true);
    void api.generateReport(mode)
      .then(() => api.reports())
      .then(setRows)
      .then(() => notify("success", "Bilingual consolidated report created."))
      .catch((reason) => showError(fullError(reason)))
      .finally(() => setGenerating(false));
  };

  type ReportRow = Record<string, unknown> & {
    id?: number; date?: string;
    markdown_path?: string; html_path?: string; pdf_path?: string;
    summary?: { original_ai_response_text_path?: string; original_ai_response_pdf_path?: string };
  };
  const typedRows = rows as ReportRow[];

  return (
    <>
      <label>
        Report period
        <select value={mode} onChange={(e) => setMode(e.target.value as "calendar" | "session")}>
          <option value="calendar">Cairo calendar day</option>
          <option value="session">EGX trading session</option>
        </select>
      </label>
      <button onClick={generate} disabled={generating}>
        {generating ? "Generating report…" : "Generate consolidated report"}
      </button>

      {typedRows.length === 0 && <p className="empty">No reports yet.</p>}
      {typedRows.map((report, i) => (
        <div key={report.id ?? i} style={{ background: "#111c2e", border: "1px solid #26364d", borderRadius: "10px", padding: "1rem", marginTop: "1rem" }}>
          <strong style={{ color: "#86efac" }}>
            Report {report.date ? String(report.date).slice(0, 16).replace("T", " ") : `#${report.id}`}
          </strong>
          <div style={{ display: "flex", flexWrap: "wrap", gap: ".5rem", marginTop: ".75rem" }}>
            {report.html_path && (
              <a href={`file:///${String(report.html_path).replace(/\\/g, "/")}`}
                target="_blank" rel="noreferrer"
                style={{ color: "#70c96a", fontSize: ".85rem" }}>
                Open HTML report
              </a>
            )}
            {report.pdf_path && (
              <a href={`file:///${String(report.pdf_path).replace(/\\/g, "/")}`}
                target="_blank" rel="noreferrer"
                style={{ color: "#70c96a", fontSize: ".85rem", marginLeft: "1rem" }}>
                Open PDF report
              </a>
            )}
            {report.summary && (report.summary as ReportRow["summary"])?.original_ai_response_pdf_path && (
              <a href={`file:///${String((report.summary as ReportRow["summary"])!.original_ai_response_pdf_path).replace(/\\/g, "/")}`}
                target="_blank" rel="noreferrer"
                style={{ color: "#94a3b8", fontSize: ".85rem", marginLeft: "1rem" }}>
                Original AI response PDF
              </a>
            )}
            {report.summary && (report.summary as ReportRow["summary"])?.original_ai_response_text_path && (
              <a href={`file:///${String((report.summary as ReportRow["summary"])!.original_ai_response_text_path).replace(/\\/g, "/")}`}
                target="_blank" rel="noreferrer"
                style={{ color: "#94a3b8", fontSize: ".85rem", marginLeft: "1rem" }}>
                Original AI response text
              </a>
            )}
          </div>
          {report.markdown_path && (
            <p style={{ color: "#475569", fontSize: ".78rem", marginTop: ".4rem", wordBreak: "break-all" }}>
              {String(report.markdown_path)}
            </p>
          )}
        </div>
      ))}
    </>
  );
}

// ── Channels ──────────────────────────────────────────────────────────────────

function Channels({ channels, api, refresh, notify, showError }: {
  channels: Channel[]; api: ApiClient;
  refresh: () => Promise<boolean>; notify: Notify; showError: ShowError;
}) {
  const [handle, setHandle] = useState("");
  const [chats, setChats] = useState<TelegramChat[]>(() => {
    localStorage.removeItem("egx.telegramChats");
    try { return JSON.parse(sessionStorage.getItem("egx.telegramChats") || "[]") as TelegramChat[]; }
    catch { return []; }
  });
  const [selectedHandles, setSelectedHandles] = useState<string[]>(() => {
    try { return JSON.parse(sessionStorage.getItem("egx.selectedTelegramChats") || "[]") as string[]; }
    catch { return []; }
  });
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [lastAnalysis, setLastAnalysis] = useState<SelectedAnalysisResult | null>(null);
  const [lookbackDays, setLookbackDays] = useState(3);

  const busy = loading || analyzing;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    void api.addChannel(handle)
      .then(() => { setHandle(""); return refresh(); })
      .then(() => notify("success", "Channel added for analysis."))
      .catch((reason) => showError(fullError(reason)))
      .finally(() => setLoading(false));
  };

  const loadChats = () => {
    setLoading(true);
    void api.telegramChats()
      .then((items) => {
        setChats(items);
        sessionStorage.setItem("egx.telegramChats", JSON.stringify(items));
        notify(items.length ? "success" : "warning",
          items.length ? `${items.length} Telegram chats loaded for this session.` : "No chats were found.");
      })
      .catch((reason) => showError(fullError(reason)))
      .finally(() => setLoading(false));
  };

  const updateSelectedHandles = (handles: string[]) => {
    setSelectedHandles(handles);
    sessionStorage.setItem("egx.selectedTelegramChats", JSON.stringify(handles));
  };

  const addChat = (chat: TelegramChat) => {
    setLoading(true);
    void api.selectTelegramChat(chat)
      .then((channel) => {
        updateSelectedHandles([...new Set([...selectedHandles, channel.handle])]);
        return refresh();
      })
      .then(() => notify("success", `${chat.title} is selected for this session.`))
      .catch((reason) => showError(fullError(reason)))
      .finally(() => setLoading(false));
  };

  const removeChat = (h: string) => {
    updateSelectedHandles(selectedHandles.filter((item) => item !== h));
    notify("success", "Chat removed from this session.");
  };

  const selected = new Set(selectedHandles);
  const selectedChannels = channels.filter((channel) => selected.has(channel.handle));

  const analyze = () => {
    const ids = selectedChannels.map((channel) => channel.id);
    if (!ids.length) return notify("warning", "Select at least one chat first.");
    setAnalyzing(true);
    void api.analyzeSelected(ids, lookbackDays)
      .then((result) => {
        setLastAnalysis(result);
        return refresh().then(() =>
          notify(result.not_stock_related.length ? "warning" : "success",
            `${result.messages_analyzed} of ${result.messages_in_window} messages freshly analyzed ` +
            `from the last ${result.lookback_days} day(s) (${result.messages_reanalyzed} re-analyzed). ` +
            `Report and local trace created.` +
            (result.not_stock_related.length ? ` No stock-related context: ${result.not_stock_related.join(", ")}.` : "")
          )
        );
      })
      .catch((reason) => showError(fullError(reason)))
      .finally(() => setAnalyzing(false));
  };

  const selectedRows = selectedChannels.map((channel) => ({
    ...channel,
    selection: <button className="secondary" onClick={() => removeChat(channel.handle)} disabled={busy}>Remove</button>,
  }));
  const chatRows = chats.map((chat) => ({
    chat: `${chat.title}${chat.username ? ` (@${chat.username})` : ""}`,
    type: chat.kind,
    selection: (
      <button disabled={busy} onClick={() => selected.has(chat.id) ? removeChat(chat.id) : addChat(chat)}>
        {selected.has(chat.id) ? "Remove" : "Select"}
      </button>
    ),
  }));

  return (
    <>
      <form className="inline" onSubmit={submit}>
        <input value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="Telegram username, without @" required />
        <button disabled={busy}>Add channel</button>
      </form>
      <button onClick={loadChats} disabled={busy}>{loading ? "Loading chats…" : "Load my Telegram chats"}</button>
      {chats.length > 0 && <Table rows={chatRows} />}

      <h3>Selected chats ({selectedChannels.length})</h3>
      <label>
        {`Analysis window: last ${lookbackDays} day${lookbackDays === 1 ? "" : "s"}`}
        <input type="range" min="1" max="5" step="1" value={lookbackDays}
          onChange={(e) => setLookbackDays(Number(e.target.value))} disabled={busy} />
      </label>
      <button onClick={analyze} disabled={busy}>
        {analyzing ? "Analyzing selected chats…" : "Analyze selected chats"}
      </button>
      <Table rows={selectedRows} />

      {lastAnalysis && (
        <section>
          <h3>Original AI response export</h3>
          <p>PDF: {lastAnalysis.report.original_ai_response_pdf_path}</p>
          <p>Text: {lastAnalysis.report.original_ai_response_text_path}</p>
          <h3>Latest analysis report</h3>
          <p>Report PDF: {lastAnalysis.report.pdf_path}</p>
          <p>Trace messages: {lastAnalysis.trace.text_path}</p>
          <p>Trace images: {lastAnalysis.trace.images_path}</p>
          <h3>EGX code details by channel</h3>
          <Table rows={lastAnalysis.stock_code_details.map((item) => ({
            code: item.ticker,
            company: item.company,
            channel: item.channel,
            occurrences: item.occurrences,
            extracted_details: item.details.map((detail) =>
              Object.entries(detail).map(([k, v]) => `${k}=${v}`).join(", ")
            ).join(" | ") || "—",
          }))} />
          <h3>EGX code summary</h3>
          <Table rows={lastAnalysis.stock_code_summary.map((item) => ({
            code: item.ticker,
            company: item.company,
            occurrences: item.occurrences,
            per_chat: Object.entries(item.by_chat).map(([chat, count]) => `${chat}: ${count}`).join(" | "),
          }))} />
          <Table rows={lastAnalysis.channel_results} />
        </section>
      )}
    </>
  );
}

// ── Recommendations ───────────────────────────────────────────────────────────

type RecommendationRow = { id: number; company: string; ticker?: string; signal: string; confidence: number; target?: number };

function Recommendations({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (!rows.length) return <p className="empty">No recommendations yet. Run an analysis to populate this page.</p>;
  const typed = rows as unknown as RecommendationRow[];
  const signalColor: Record<string, string> = { BUY: "#86efac", SELL: "#fca5a5", HOLD: "#fde68a" };
  const signalBg: Record<string, string> = { BUY: "#1a3d24", SELL: "#3d1a1a", HOLD: "#2e2a14" };
  return (
    <div className="table">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Company</th>
            <th>Ticker</th>
            <th>Signal</th>
            <th style={{ textAlign: "right" }}>Confidence</th>
            <th style={{ textAlign: "right" }}>Target</th>
          </tr>
        </thead>
        <tbody>
          {typed.map((row, i) => (
            <tr key={row.id}>
              <td style={{ color: "#94a3b8", fontSize: ".8rem" }}>{i + 1}</td>
              <td><strong>{row.company}</strong></td>
              <td style={{ color: "#94a3b8" }}>{row.ticker || "—"}</td>
              <td>
                <span style={{
                  display: "inline-block", padding: ".2rem .55rem", borderRadius: "4px",
                  fontSize: ".78rem", fontWeight: 700,
                  background: signalBg[row.signal] ?? "#172033",
                  color: signalColor[row.signal] ?? "#e5e7eb",
                }}>
                  {row.signal}
                </span>
              </td>
              <td style={{ textAlign: "right" }}>{(row.confidence * 100).toFixed(0)}%</td>
              <td style={{ textAlign: "right" }}>{row.target ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Search ────────────────────────────────────────────────────────────────────

function Search({ api, onResult, showError }: {
  api: ApiClient; onResult: (rows: Array<Record<string, unknown>>) => void;
  notify: Notify; showError: ShowError;
}) {
  const [query, setQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSearching(true);
    void api.search(query)
      .then(onResult)
      .catch((reason) => showError(fullError(reason)))
      .finally(() => setSearching(false));
  };
  return (
    <form className="inline" onSubmit={submit}>
      <input value={query} onChange={(e) => setQuery(e.target.value)}
        placeholder="Ask about CIB, TMG, or market changes" required />
      <button disabled={searching}>{searching ? "Searching…" : "Search"}</button>
    </form>
  );
}

// ── Model selector ────────────────────────────────────────────────────────────

function ModelSelector({ api, configured, selected, onChange, showError }: {
  api: ApiClient; configured: boolean; selected: string;
  onChange: (value: string) => void; showError: ShowError;
}) {
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (announce: boolean) => {
    if (!configured) {
      if (announce) showError("Save an API key for the selected provider first.");
      return;
    }
    setLoading(true);
    try {
      const loaded = await api.models();
      setModels(loaded);
      if (announce && loaded.length === 0) {
        showError("No compatible analysis models are available to this API key.");
      }
    } catch (reason) {
      showError(`Could not load models: ${fullError(reason)}`);
    } finally {
      setLoading(false);
    }
  }, [api, configured, showError]);

  useEffect(() => { void load(false); }, [load]);

  return (
    <label>
      Analysis model
      <div className="model-row">
        <select value={selected} onChange={(e) => onChange(e.target.value)}>
          <option value={selected}>{selected || "Choose a model"}</option>
          {models.filter((m) => m !== selected).map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <button type="button" onClick={() => void load(true)} disabled={!configured || loading}>
          {loading ? "Loading…" : "Load available models"}
        </button>
      </div>
    </label>
  );
}

// ── CloudSettings ─────────────────────────────────────────────────────────────

function CloudSettings({ api, status, onSaved, notify, showError, checkingUpdate, onCheckForUpdates }: {
  api: ApiClient; status: SettingsStatus | null; onSaved: () => Promise<boolean>;
  notify: Notify; showError: ShowError; checkingUpdate: boolean; onCheckForUpdates: () => void;
}) {
  const [values, setValues] = useState<SettingsInput>({
    ai_provider: status?.ai_provider || "qwen",
    openai_model: status?.openai_model || "qwen3-vl-plus",
    analysis_instructions: status?.analysis_instructions || "",
  });
  const [editingProviderKey, setEditingProviderKey] = useState(false);
  const [editingTelegram, setEditingTelegram] = useState(false);
  const [saving, setSaving] = useState(false);
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [diagnostics, setDiagnostics] = useState<DiagnosticEntry[]>([]);
  const [loadingDiagnostics, setLoadingDiagnostics] = useState(false);
  const [contentStatus, setContentStatus] = useState<ContentUpdateStatus | null>(null);
  const [checkingContent, setCheckingContent] = useState(false);
  const [appVersion, setAppVersion] = useState("");

  const provider = (values.ai_provider || status?.ai_provider || "qwen") as AiProvider;

  const providerDetails: Record<AiProvider, { label: string; placeholder: string; key: keyof SettingsInput }> = {
    qwen: { label: "Qwen Cloud", placeholder: "sk-...", key: "qwen_api_key" },
    openrouter: { label: "OpenRouter", placeholder: "sk-or-...", key: "openrouter_api_key" },
    huggingface: { label: "Hugging Face", placeholder: "hf_...", key: "huggingface_api_key" },
    openai: { label: "OpenAI", placeholder: "sk-...", key: "openai_api_key" },
  };
  const currentProvider = providerDetails[provider];

  useEffect(() => { void getVersion().then(setAppVersion).catch(() => setAppVersion("Unknown")); }, []);
  useEffect(() => { void api.contentUpdates().then(setContentStatus).catch(() => setContentStatus(null)); }, [api]);
  useEffect(() => {
    if (status) setValues((cur) => ({
      ...cur,
      ai_provider: status.ai_provider,
      openai_model: status.openai_model,
      analysis_instructions: status.analysis_instructions,
    }));
  }, [status]);

  const save = (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    void api.saveSettings(values)
      .then(onSaved)
      .then(() => {
        setValues((cur) => ({ ai_provider: cur.ai_provider, openai_model: cur.openai_model, analysis_instructions: cur.analysis_instructions }));
        setEditingProviderKey(false);
        setEditingTelegram(false);
        notify("success", "Settings saved securely on this computer.");
      })
      .catch((reason) => showError(`Could not save settings: ${fullError(reason)}`))
      .finally(() => setSaving(false));
  };

  const chooseProvider = (next: AiProvider) => {
    const defaultModel = next === "qwen" ? "qwen3-vl-plus" : next === "openrouter" ? "openrouter/free" : "";
    setValues((cur) => ({ ...cur, ai_provider: next, openai_model: defaultModel }));
    setEditingProviderKey(false);
  };

  const replaceKey = () => {
    if (editingProviderKey) setValues((cur) => ({ ...cur, [currentProvider.key]: undefined }));
    setEditingProviderKey((cur) => !cur);
  };

  return (
    <div className="settings">
      <form onSubmit={save}>
        <p>Cloud provider keys are encrypted and stored only on this computer. No AI model is downloaded locally.</p>

        <label>
          AI provider
          <select value={provider} onChange={(e) => chooseProvider(e.target.value as AiProvider)}>
            <option value="qwen">Qwen Cloud {"—"} default for Arabic and charts</option>
            <option value="openrouter">OpenRouter {"—"} free models available</option>
            <option value="huggingface">Hugging Face Inference Providers</option>
            <option value="openai">OpenAI</option>
          </select>
        </label>

        <div className="credential-header">
          <div>
            <strong>{currentProvider.label}</strong>
            <span>{status?.ai_provider === provider && status.ai_configured ? "API key saved" : "API key not configured"}</span>
          </div>
          <button type="button" className="secondary" onClick={replaceKey}>
            {editingProviderKey ? "Cancel" : status?.ai_provider === provider && status.ai_configured ? "Replace API key" : "Add API key"}
          </button>
        </div>
        {editingProviderKey && (
          <label>
            {`New ${currentProvider.label} API key`}
            <input type="password" autoComplete="new-password" placeholder={currentProvider.placeholder}
              value={(values[currentProvider.key] as string) || ""}
              onChange={(e) => setValues((cur) => ({ ...cur, [currentProvider.key]: e.target.value }))} required />
          </label>
        )}

        {provider === "qwen" && (
          <label>
            Qwen Cloud endpoint
            <input type="url" list="qwen-endpoints"
              value={values.qwen_base_url || "https://dashscope.aliyuncs.com/compatible-mode/v1"}
              onChange={(e) => setValues((cur) => ({ ...cur, qwen_base_url: e.target.value }))} required />
            <datalist id="qwen-endpoints">
              <option value="https://dashscope.aliyuncs.com/compatible-mode/v1">China (Beijing)</option>
              <option value="https://dashscope-intl.aliyuncs.com/compatible-mode/v1">Singapore</option>
              <option value="https://dashscope-us.aliyuncs.com/compatible-mode/v1">US (Virginia)</option>
            </datalist>
            <span className="credential-note">
              The key and endpoint must be from the same Model Studio region and pay-as-you-go billing plan.
              You can also enter your workspace-dedicated endpoint.
            </span>
          </label>
        )}

        <ModelSelector
          api={api}
          configured={Boolean(status?.ai_provider === provider && status.ai_configured)}
          selected={values.openai_model || ""}
          onChange={(openai_model) => setValues((cur) => ({ ...cur, openai_model }))}
          showError={showError}
        />

        <label>
          Primary analysis prompt
          <textarea
            value={values.analysis_instructions || ""}
            onChange={(e) => setValues((cur) => ({ ...cur, analysis_instructions: e.target.value }))}
            placeholder="For example: prioritize EGX table rows, show entry and targets exactly as posted, and flag conflicting channel details."
            rows={6}
          />
          <span className="credential-note">
            When filled, this replaces the built-in analysis prompt for every request. Leave it empty to use the built-in prompt.
            The required structured output format remains enforced.
          </span>
        </label>

        <div className="credential-header">
          <div>
            <strong>Telegram</strong>
            <span>{status?.telegram_configured ? "API credentials saved" : "API credentials not configured"}</span>
          </div>
          <button type="button" className="secondary" onClick={() => {
            if (editingTelegram) setValues(({ telegram_api_id, telegram_api_hash, ...cur }) => cur);
            setEditingTelegram((cur) => !cur);
          }}>
            {editingTelegram ? "Cancel" : status?.telegram_configured ? "Replace Telegram credentials" : "Add Telegram credentials"}
          </button>
        </div>
        {editingTelegram && (
          <>
            <label>
              New Telegram API ID
              <input type="number" placeholder="From my.telegram.org"
                value={values.telegram_api_id || ""}
                onChange={(e) => setValues((cur) => ({ ...cur, telegram_api_id: Number(e.target.value) || undefined }))} required />
            </label>
            <label>
              New Telegram API hash
              <input type="password" autoComplete="new-password" placeholder="API hash"
                value={values.telegram_api_hash || ""}
                onChange={(e) => setValues((cur) => ({ ...cur, telegram_api_hash: e.target.value }))} required />
            </label>
            <p className="credential-note">
              Changing Telegram credentials signs this computer out of Telegram. Connect it again below after saving.
            </p>
          </>
        )}

        <button disabled={saving}>{saving ? "Saving…" : "Save settings"}</button>
      </form>

      <article className="app-version">
        <h3>EGX Intelligence</h3>
        <p>Version {appVersion || "Loading…"}</p>
      </article>

      <article className="content-updates">
        <h3>Analysis content updates</h3>
        <p>Signed prompt and stock-alias updates install without rebuilding or reinstalling the desktop application.</p>
        <p>{contentStatus?.version ? `Installed content pack: ${contentStatus.version}` : "Using built-in analysis content."}</p>
        <button type="button" disabled={checkingContent || contentStatus?.enabled === false}
          onClick={() => {
            setCheckingContent(true);
            void api.checkContentUpdates()
              .then((result) => {
                notify("success", result.updated ? `Content pack ${result.version} installed.` : `Content pack ${result.version} is already installed.`);
                return api.contentUpdates();
              })
              .then(setContentStatus)
              .catch((reason) => showError(`Could not update analysis content: ${fullError(reason)}`))
              .finally(() => setCheckingContent(false));
          }}>
          {checkingContent ? "Checking content…" : "Check analysis content"}
        </button>
      </article>

      <form className="update-settings" onSubmit={(e) => { e.preventDefault(); onCheckForUpdates(); }}>
        <h3>Application updates</h3>
        <p>Checks for a signed EGX Intelligence update and keeps your local data unchanged.</p>
        <button disabled={checkingUpdate}>{checkingUpdate ? "Checking…" : "Check for updates"}</button>
      </form>

      <article className="diagnostics">
        <h3>Diagnostics</h3>
        <p>Stores local request results and error traces. API keys, codes, and passwords are never logged.</p>
        <button type="button" className="secondary" disabled={loadingDiagnostics}
          onClick={() => {
            setLoadingDiagnostics(true);
            void api.diagnostics()
              .then((result) => {
                setDiagnostics(result.entries);
                notify("success", "Recent diagnostics loaded.");
              })
              .catch((reason) => showError(`Could not load diagnostics: ${fullError(reason)}`))
              .finally(() => setLoadingDiagnostics(false));
          }}>
          {loadingDiagnostics ? "Loading diagnostics…" : "View recent diagnostics"}
        </button>
        {diagnostics.length > 0 && (
          <pre>{diagnostics.map((entry) =>
            `${entry.timestamp || ""} ${entry.level} ${entry.event} ${entry.method || ""} ${entry.path || ""} ${entry.status_code || ""} ${entry.error_type || ""}`
          ).join("\n")}</pre>
        )}
      </article>

      {!status?.telegram_authorized && (
        <form onSubmit={(e) => {
          e.preventDefault();
          setSendingCode(true);
          void api.requestTelegramCode(phone)
            .then(() => { setCodeSent(true); notify("success", "Telegram code sent. Enter it below."); })
            .catch((reason) => showError(`Could not send Telegram code: ${fullError(reason)}`))
            .finally(() => setSendingCode(false));
        }}>
          <h3>Connect Telegram</h3>
          <label>
            Phone number
            <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+201..." required />
          </label>
          <button disabled={sendingCode}>{sendingCode ? "Sending code…" : "Send code"}</button>
        </form>
      )}

      {!status?.telegram_authorized && codeSent && (
        <form onSubmit={(e) => {
          e.preventDefault();
          setVerifying(true);
          void api.verifyTelegramCode(code, password || undefined)
            .then(() => onSaved())
            .then(() => notify("success", "Telegram connected and saved for future launches."))
            .catch((reason) => showError(`Telegram connection failed: ${fullError(reason)}`))
            .finally(() => setVerifying(false));
        }}>
          <label>
            Verification code
            <input value={code} onChange={(e) => setCode(e.target.value)} required />
          </label>
          <label>
            Two-step password (only if enabled)
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          <button disabled={verifying}>{verifying ? "Verifying…" : "Verify code"}</button>
        </form>
      )}
    </div>
  );
}

// ── Update banner ─────────────────────────────────────────────────────────────

function UpdateBanner({ update, downloading, progress, onInstall, onDismiss }: {
  update: UpdateCandidate; downloading: boolean; progress: number | null;
  onInstall: () => void; onDismiss: () => void;
}) {
  return (
    <article className="update-banner">
      <div>
        <strong>Update available: {update.version}</strong>
        <p>{update.body || "A newer, signed version of EGX Intelligence is ready."}</p>
        {downloading && <p>{progress === null ? "Downloading update…" : `Downloading update: ${progress}%`}</p>}
      </div>
      <div className="update-actions">
        <button onClick={onInstall} disabled={downloading}>{downloading ? "Installing…" : "Download and install"}</button>
        <button className="secondary" onClick={onDismiss} disabled={downloading}>Later</button>
      </div>
    </article>
  );
}

// ── Generic components ────────────────────────────────────────────────────────

function Metric({ value, label }: { value: number; label: string }) {
  return <article><b>{value}</b><span>{label}</span></article>;
}

function Table({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (!rows.length) return <p className="empty">No records yet.</p>;
  const headers = Object.keys(rows[0]);
  return (
    <div className="table">
      <table>
        <thead>
          <tr>{headers.map((h) => <th key={h}>{h.replaceAll("_", " ")}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {headers.map((h) => (
                <td key={h}>{isValidElement(row[h]) ? row[h] : String(row[h] ?? "—")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fullError(error: unknown): string {
  return error instanceof Error ? error.message : String(error) || "Request failed";
}

function updateErrorMessage(error: unknown): string {
  const detail = fullError(error);
  return /endpoint|updater|config/i.test(detail)
    ? "Updates are not configured yet. Run the one-time updater setup before publishing the first release."
    : `Could not check for updates: ${detail}`;
}
