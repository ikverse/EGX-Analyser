import { FormEvent, isValidElement, useCallback, useEffect, useMemo, useState } from "react";
import type React from "react";
import { invoke } from "@tauri-apps/api/core";
import { getVersion } from "@tauri-apps/api/app";
import { check } from "@tauri-apps/plugin-updater";

import {
  AiProvider, ApiClient, Channel, Consensus, ContentUpdateStatus,
  DiagnosticEntry, SelectedAnalysisResult, SettingsInput, SettingsStatus, TelegramChat,
  StockSourceRow, StockSummaryRow,
} from "./api";

type Page = "Dashboard" | "Channels" | "Results" | "Reports" | "Settings";
type ResultTab = "Recommendations" | "Search";
type Toast = { kind: "success" | "warning"; text: string } | null;
type UpdateCandidate = {
  version: string;
  body?: string | null;
  downloadAndInstall: (onEvent: (event: { event: string; data: { contentLength?: number; chunkLength?: number } }) => void) => Promise<void>;
};

const pages: Page[] = ["Dashboard", "Channels", "Results", "Reports", "Settings"];

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
  const [resultTab, setResultTab] = useState<ResultTab>("Recommendations");
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
    return () => {
      cancelled = true;
      if (retryTimer) window.clearTimeout(retryTimer);
    };
  }, [api]);

  useEffect(() => {
    if (!connected) return;
    const timer = window.setTimeout(() => void checkForUpdates(false), 1200);
    return () => window.clearTimeout(timer);
  }, [connected]);

  useEffect(() => {
    if (connected && page === "Results" && resultTab === "Recommendations") {
      setRows([]);
      void api.recommendations().then(setRows);
    }
    if (connected && page === "Reports") {
      setRows([]);
      void api.reports().then(setRows);
    }
  }, [api, connected, page, resultTab]);

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
              <span className="online">
                <span className="online-dot" />
                Local engine online
              </span>
            </div>
            <div className="header-actions">
              {page === "Dashboard" && (
                <DashboardCheckButton api={api} refresh={refresh} notify={notify} showError={showError} />
              )}
              <button className="secondary" onClick={() => void refresh()}>Refresh</button>
            </div>
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

          {page === "Dashboard" && <Dashboard channels={channels} consensus={consensus} />}
          {page === "Channels" && <Channels channels={channels} api={api} refresh={refresh} notify={notify} showError={showError} />}
          {page === "Results" && (
            <Results
              api={api}
              rows={rows}
              setRows={setRows}
              tab={resultTab}
              setTab={setResultTab}
              notify={notify}
              showError={showError}
            />
          )}
          {page === "Reports" && <Reports api={api} rows={rows} setRows={setRows} notify={notify} showError={showError} />}
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

      {errorModal && <ErrorModal message={errorModal} onClose={() => setErrorModal(null)} />}

      {toast && (
        <div className={`toast ${toast.kind}`} role="status">
          <strong>{toast.kind}</strong>
          <span>{toast.text}</span>
          <button onClick={() => setToast(null)} aria-label="Dismiss">✕</button>
        </div>
      )}
    </>
  );
}

// ── Shared types ──────────────────────────────────────────────────────────────

type Notify = (kind: "success" | "warning", text: string) => void;

const SIGNAL_COLOR: Record<string, string> = { BUY: "#86efac", SELL: "#fca5a5", HOLD: "#fde68a" };
const SIGNAL_BG: Record<string, string> = { BUY: "#1a3d24", SELL: "#3d1a1a", HOLD: "#2e2a14" };
type ShowError = (message: string) => void;

// ── Dashboard check button (lives in header) ──────────────────────────────────

function DashboardCheckButton({ api, refresh, notify, showError }: {
  api: ApiClient; refresh: () => Promise<boolean>; notify: Notify; showError: ShowError;
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
    <button onClick={run} disabled={running}>
      {running ? "Checking Telegram…" : "Check Telegram now"}
    </button>
  );
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

function Dashboard({ channels, consensus }: {
  channels: Channel[]; consensus: Consensus[];
}) {
  return (
    <>
      <div className="metrics">
        <Metric value={consensus.length} label="Stocks discussed" />
        <Metric value={consensus.filter((item) => item.sentiment === "BUY").length} label="Buy consensus" />
        <Metric value={channels.filter((item) => item.active).length} label="Active channels" />
      </div>
      {consensus.length === 0
        ? <p className="empty">No consensus data yet. Run a Telegram check to populate this page.</p>
        : (
          <div className="table">
            <table>
              <thead>
                <tr>
                  {Object.keys(consensus[0]).map((h) => (
                    <th key={h}>{h.replaceAll("_", " ")}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {consensus.map((row, i) => (
                  <tr key={i}>
                    {Object.entries(row).map(([k, v]) => (
                      <td key={k}>
                        {k === "sentiment" ? (
                          <span style={{
                            display: "inline-block", padding: ".2rem .55rem", borderRadius: "4px",
                            fontSize: ".78rem", fontWeight: 700,
                            background: SIGNAL_BG[String(v)] ?? "#172033",
                            color: SIGNAL_COLOR[String(v)] ?? "#e5e7eb",
                          }}>
                            {String(v ?? "—")}
                          </span>
                        ) : String(v ?? "—")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      }
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
      <div className="report-controls">
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
      </div>

      {typedRows.length === 0 && <p className="empty">No reports yet.</p>}
      {typedRows.map((report, i) => (
        <div key={report.id ?? i} className="report-card">
          <strong className="report-card-title">
            {report.date ? String(report.date).slice(0, 16).replace("T", " ") : `Report #${report.id}`}
          </strong>
          <div className="report-links">
            {report.html_path && (
              <a href={`file:///${String(report.html_path).replace(/\\/g, "/")}`}
                target="_blank" rel="noreferrer" className="report-link">
                HTML report
              </a>
            )}
            {report.pdf_path && (
              <a href={`file:///${String(report.pdf_path).replace(/\\/g, "/")}`}
                target="_blank" rel="noreferrer" className="report-link">
                PDF report
              </a>
            )}
            {report.summary?.original_ai_response_pdf_path && (
              <a href={`file:///${String(report.summary.original_ai_response_pdf_path).replace(/\\/g, "/")}`}
                target="_blank" rel="noreferrer" className="report-link muted">
                AI response PDF
              </a>
            )}
            {report.summary?.original_ai_response_text_path && (
              <a href={`file:///${String(report.summary.original_ai_response_text_path).replace(/\\/g, "/")}`}
                target="_blank" rel="noreferrer" className="report-link muted">
                AI response text
              </a>
            )}
          </div>
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
      <div className="channels-section">
        <h3 className="section-heading">Add channel</h3>
        <form className="inline" onSubmit={submit}>
          <input value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="Telegram username, without @" required />
          <button disabled={busy}>Add channel</button>
        </form>
        <button className="secondary" onClick={loadChats} disabled={busy}>
          {loading ? "Loading chats…" : "Load my Telegram chats"}
        </button>
        {chats.length > 0 && <Table rows={chatRows} />}
      </div>

      <div className="channels-section">
        <h3 className="section-heading">Analyze selected chats ({selectedChannels.length})</h3>
        <div className="lookback-row">
          <label className="lookback-label">
            Analysis window
            <span className="lookback-value">{lookbackDays} day{lookbackDays === 1 ? "" : "s"}</span>
          </label>
          <input type="range" min="1" max="5" step="1" value={lookbackDays}
            onChange={(e) => setLookbackDays(Number(e.target.value))} disabled={busy}
            className="lookback-slider" />
        </div>
        <button onClick={analyze} disabled={busy}>
          {analyzing ? "Analyzing selected chats…" : "Analyze selected chats"}
        </button>
        <Table rows={selectedRows} />
      </div>

      {lastAnalysis && (
        <AnalysisResultTable
          summary={lastAnalysis.stock_code_summary}
          details={lastAnalysis.stock_code_details}
          channelResults={lastAnalysis.channel_results}
          reportHtmlPath={lastAnalysis.report.html_path}
          reportPdfPath={lastAnalysis.report.pdf_path}
          aiResponsePdfPath={lastAnalysis.report.original_ai_response_pdf_path}
          aiResponseTextPath={lastAnalysis.report.original_ai_response_text_path}
          tracePath={lastAnalysis.trace.text_path}
        />
      )}
    </>
  );
}

// ── Results (merged Recommendations + Search) ─────────────────────────────────

function Results({ api, rows, setRows, tab, setTab, notify, showError }: {
  api: ApiClient; rows: Array<Record<string, unknown>>;
  setRows: (rows: Array<Record<string, unknown>>) => void;
  tab: ResultTab; setTab: (t: ResultTab) => void;
  notify: Notify; showError: ShowError;
}) {
  return (
    <>
      <div className="tab-bar">
        <button className={tab === "Recommendations" ? "tab active" : "tab"} onClick={() => setTab("Recommendations")}>
          Recommendations
        </button>
        <button className={tab === "Search" ? "tab active" : "tab"} onClick={() => setTab("Search")}>
          Search
        </button>
      </div>
      {tab === "Recommendations" && <Recommendations rows={rows} />}
      {tab === "Search" && <Search api={api} onResult={setRows} notify={notify} showError={showError} />}
    </>
  );
}

// ── Analysis result table ─────────────────────────────────────────────────────

const PRICE_FIELDS: Array<{ key: string; label: string }> = [
  { key: "buy_price",           label: "Entry" },
  { key: "target_1",            label: "TP1" },
  { key: "target_2",            label: "TP2" },
  { key: "stop_loss",           label: "Stop" },
  { key: "support",             label: "Support" },
  { key: "resistance",          label: "Resistance" },
  { key: "expected_return_pct", label: "Return %" },
  { key: "risk_pct",            label: "Risk %" },
  { key: "date",                label: "Date" },
];

function num(v: string | undefined): string {
  if (!v || v === "None" || v === "null") return "—";
  const n = parseFloat(v);
  return isNaN(n) ? v : String(n);
}

function AnalysisResultTable({ summary, details, channelResults, reportHtmlPath, reportPdfPath, aiResponsePdfPath, aiResponseTextPath, tracePath }: {
  summary: StockSummaryRow[];
  details: StockSourceRow[];
  channelResults: Array<{ channel: string; status: string; messages: number; recommendations: number; stock_codes: number }>;
  reportHtmlPath: string;
  reportPdfPath: string;
  aiResponsePdfPath: string;
  aiResponseTextPath: string;
  tracePath: string;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    const s = new Set<string>();
    summary.forEach((item) => s.add(item.ticker));
    return s;
  });

  const toggle = (ticker: string) =>
    setExpanded((prev) => { const next = new Set(prev); next.has(ticker) ? next.delete(ticker) : next.add(ticker); return next; });

  const byTicker = new Map<string, StockSourceRow[]>();
  details.forEach((row) => {
    const rows = byTicker.get(row.ticker) ?? [];
    rows.push(row);
    byTicker.set(row.ticker, rows);
  });

  const stocks = summary.map((s) => ({ ...s, sources: byTicker.get(s.ticker) ?? [] }));

  const fileLink = (path: string, label: string, muted = false) => (
    <a href={`file:///${path.replace(/\\/g, "/")}`} target="_blank" rel="noreferrer"
      className={`analysis-file-link${muted ? " muted" : ""}`}>
      {label}
    </a>
  );

  const statusColor: Record<string, string> = {
    recommendations_found: "#86efac", stock_codes_found: "#86efac",
    stock_related_no_recommendations: "#fde68a", not_stock_related: "#94a3b8", no_recent_messages: "#475569",
  };

  return (
    <div style={{ marginTop: "1.5rem" }}>
      <div className="analysis-links-bar">
        <span className="analysis-links-label">Reports:</span>
        {fileLink(reportHtmlPath, "HTML report")}
        {fileLink(reportPdfPath, "PDF report")}
        {fileLink(aiResponsePdfPath, "Original AI response PDF", true)}
        {fileLink(aiResponseTextPath, "Original AI response text", true)}
        {fileLink(tracePath, "Analysis trace", true)}
      </div>

      {channelResults.length > 0 && (
        <div className="channel-status-bar">
          {channelResults.map((cr) => (
            <span key={cr.channel} className="channel-status-chip" style={{ color: statusColor[cr.status] ?? "#94a3b8" }}>
              {cr.channel} · {cr.messages} msg · {cr.recommendations} rec · {cr.stock_codes} codes
            </span>
          ))}
        </div>
      )}

      {stocks.length === 0 && (
        <p style={{ color: "#94a3b8", fontStyle: "italic" }}>No EGX stock codes were found in this analysis window.</p>
      )}

      {stocks.map((stock) => {
        const open = expanded.has(stock.ticker);
        return (
          <div key={stock.ticker} className="stock-card">
            <button className="stock-card-header" onClick={() => toggle(stock.ticker)}>
              <span className="stock-card-chevron">{open ? "▾" : "▸"}</span>
              <span className="stock-card-ticker">{stock.ticker}</span>
              <span className="stock-card-company">{stock.company}</span>
              {stock.company_ar && (
                <span className="stock-card-company-ar">{stock.company_ar}</span>
              )}
              <span className="stock-card-mentions" style={{
                background: stock.occurrences >= 3 ? "#1a3d24" : stock.occurrences === 2 ? "#2e2a14" : "#172033",
                color: stock.occurrences >= 3 ? "#86efac" : stock.occurrences === 2 ? "#fde68a" : "#94a3b8",
                marginLeft: stock.company_ar ? "1rem" : "auto",
              }}>
                {stock.occurrences} mention{stock.occurrences !== 1 ? "s" : ""}
              </span>
            </button>

            {open && stock.sources.length > 0 && (
              <div className="stock-card-body-table">
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: ".83rem" }}>
                  <thead>
                    <tr style={{ background: "#0f1e33" }}>
                      <th style={thStyle}>Source / Channel</th>
                      {PRICE_FIELDS.map((f) => (
                        <th key={f.key} style={{ ...thStyle, textAlign: "right" }}>{f.label}</th>
                      ))}
                      <th style={thStyle}>Arabic summary</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stock.sources.map((src, si) =>
                      src.details.length === 0 ? (
                        <tr key={si} style={si % 2 === 0 ? evenRow : oddRow}>
                          <td style={tdStyle}><strong style={{ color: "#86efac" }}>{src.channel}</strong></td>
                          {PRICE_FIELDS.map((f) => <td key={f.key} style={{ ...tdStyle, textAlign: "right", color: "#475569" }}>—</td>)}
                          <td style={tdStyle} />
                        </tr>
                      ) : src.details.map((detail, di) => {
                        const arabicSummary = detail["analysis_summary_ar"] || "";
                        const isFirst = di === 0;
                        return (
                          <tr key={`${si}-${di}`} style={(si + di) % 2 === 0 ? evenRow : oddRow}>
                            {isFirst ? (
                              <td style={{ ...tdStyle, verticalAlign: "top" }} rowSpan={src.details.length}>
                                <strong style={{ color: "#86efac" }}>{src.channel}</strong>
                                {src.occurrences > 1 && (
                                  <span style={{ color: "#475569", fontSize: ".75rem", display: "block" }}>
                                    {src.occurrences} entries
                                  </span>
                                )}
                              </td>
                            ) : null}
                            {PRICE_FIELDS.map((f) => (
                              <td key={f.key} style={{ ...tdStyle, textAlign: "right", color: f.key === "risk_pct" && detail[f.key] ? "#fca5a5" : f.key.startsWith("target") || f.key === "expected_return_pct" ? "#86efac" : "#e5e7eb" }}>
                                {f.key === "date" ? (detail[f.key] ? String(detail[f.key]).slice(0, 10) : "—") : num(detail[f.key])}
                              </td>
                            ))}
                            <td style={{ ...tdStyle, direction: "rtl", textAlign: "right", color: "#94a3b8", fontSize: ".8rem", maxWidth: "220px" }}>
                              {arabicSummary || ""}
                            </td>
                          </tr>
                        );
                      })
                    )}
                    {(() => {
                      const notes = stock.sources.find((s) => s.notes)?.notes;
                      if (!notes) return null;
                      const colSpan = 2 + PRICE_FIELDS.length;
                      return (
                        <tr style={{ background: "#0a1628", borderTop: "2px solid #26364d" }}>
                          <td style={{ ...tdStyle, paddingTop: ".65rem", paddingBottom: ".65rem", color: "#94a3b8", fontWeight: 600, whiteSpace: "nowrap", fontSize: ".8rem" }}>
                            Notes
                          </td>
                          <td colSpan={colSpan} style={{ ...tdStyle, color: "#cbd5e1", fontSize: ".83rem", lineHeight: 1.6, paddingTop: ".65rem", paddingBottom: ".65rem" }}>
                            {notes}
                          </td>
                        </tr>
                      );
                    })()}
                  </tbody>
                </table>
              </div>
            )}

            {open && stock.sources.length === 0 && (
              <p className="stock-card-empty">No structured price data extracted for this code.</p>
            )}
          </div>
        );
      })}
    </div>
  );
}

const thStyle: React.CSSProperties = {
  padding: ".55rem .75rem", color: "#94a3b8", fontWeight: 600,
  borderBottom: "1px solid #26364d", whiteSpace: "nowrap", textAlign: "left",
};
const tdStyle: React.CSSProperties = {
  padding: ".5rem .75rem", borderBottom: "1px solid #1e2d42", verticalAlign: "middle",
};
const evenRow: React.CSSProperties = { background: "#111c2e" };
const oddRow: React.CSSProperties  = { background: "#0f1a2e" };

// ── Recommendations ───────────────────────────────────────────────────────────

type RecommendationRow = { id: number; company: string; ticker?: string; signal: string; confidence: number; target?: number };

function Recommendations({ rows }: { rows: Array<Record<string, unknown>> }) {
  if (!rows.length) return <p className="empty">No recommendations yet. Run an analysis to populate this page.</p>;
  const typed = rows as unknown as RecommendationRow[];
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
                  background: SIGNAL_BG[row.signal] ?? "#172033",
                  color: SIGNAL_COLOR[row.signal] ?? "#e5e7eb",
                }}>
                  {row.signal}
                </span>
              </td>
              <td style={{ textAlign: "right" }}>{row.confidence != null ? `${(row.confidence * 100).toFixed(0)}%` : "—"}</td>
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
          {loading ? "Loading…" : "Load models"}
        </button>
      </div>
    </label>
  );
}

// ── CloudSettings ─────────────────────────────────────────────────────────────

function SettingsSection({ title, description, open, onToggle, children }: {
  title: string; description?: string; open: boolean; onToggle: () => void; children: React.ReactNode;
}) {
  return (
    <div className="settings-section">
      <button type="button" className="settings-section-header" onClick={onToggle}>
        <span>{title}</span>
        <span className="settings-section-chevron">{open ? "▾" : "▸"}</span>
      </button>
      {description && !open && <p className="settings-section-desc">{description}</p>}
      {open && <div className="settings-section-body">{children}</div>}
    </div>
  );
}

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
  const [openSection, setOpenSection] = useState<string>("ai");

  const toggleSection = (key: string) => setOpenSection((cur) => cur === key ? "" : key);

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

      <SettingsSection title="AI Provider" description={`${providerDetails[provider].label} · ${status?.ai_configured ? "configured" : "not configured"}`} open={openSection === "ai"} onToggle={() => toggleSection("ai")}>
        <form onSubmit={save}>
          <p>Cloud provider keys are encrypted and stored only on this computer. No AI model is downloaded locally.</p>
          <label>
            AI provider
            <select value={provider} onChange={(e) => chooseProvider(e.target.value as AiProvider)}>
              <option value="qwen">Qwen Cloud — default for Arabic and charts</option>
              <option value="openrouter">OpenRouter — free models available</option>
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
              When filled, this replaces the built-in analysis prompt. Leave empty to use the built-in prompt.
            </span>
          </label>
          <button disabled={saving}>{saving ? "Saving…" : "Save settings"}</button>
        </form>
      </SettingsSection>

      <SettingsSection title="Telegram" description={status?.telegram_configured ? (status.telegram_authorized ? "Connected" : "Credentials saved — not authorized") : "Not configured"} open={openSection === "telegram"} onToggle={() => toggleSection("telegram")}>
        <form onSubmit={save}>
          <div className="credential-header">
            <div>
              <strong>Telegram</strong>
              <span>{status?.telegram_configured ? "API credentials saved" : "API credentials not configured"}</span>
            </div>
            <button type="button" className="secondary" onClick={() => {
              if (editingTelegram) setValues(({ telegram_api_id, telegram_api_hash, ...cur }) => cur);
              setEditingTelegram((cur) => !cur);
            }}>
              {editingTelegram ? "Cancel" : status?.telegram_configured ? "Replace credentials" : "Add credentials"}
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
              <p className="credential-note">Changing credentials signs this computer out of Telegram.</p>
            </>
          )}
          {(editingTelegram) && <button disabled={saving}>{saving ? "Saving…" : "Save credentials"}</button>}
        </form>

        {!status?.telegram_authorized && (
          <form style={{ marginTop: "1rem" }} onSubmit={(e) => {
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
          <form style={{ marginTop: "1rem" }} onSubmit={(e) => {
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
      </SettingsSection>

      <SettingsSection title="Updates" description={`App v${appVersion || "…"} · ${contentStatus?.version ? `Content pack ${contentStatus.version}` : "Built-in content"}`} open={openSection === "updates"} onToggle={() => toggleSection("updates")}>
        <div className="settings-subsection">
          <strong>Application updates</strong>
          <p>Checks for a signed EGX Intelligence update and keeps your local data unchanged.</p>
          <button type="button" disabled={checkingUpdate} onClick={onCheckForUpdates}>
            {checkingUpdate ? "Checking…" : "Check for updates"}
          </button>
        </div>
        <div className="settings-subsection">
          <strong>Analysis content updates</strong>
          <p>Signed prompt and stock-alias updates install without rebuilding the application.</p>
          <p className="credential-note">{contentStatus?.version ? `Installed: ${contentStatus.version}` : "Using built-in analysis content."}</p>
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
        </div>
      </SettingsSection>

      <SettingsSection title="Diagnostics" description="Local request logs and error traces" open={openSection === "diagnostics"} onToggle={() => toggleSection("diagnostics")}>
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
          {loadingDiagnostics ? "Loading…" : "View recent diagnostics"}
        </button>
        {diagnostics.length > 0 && (
          <pre>{diagnostics.map((entry) =>
            `${entry.timestamp || ""} ${entry.level} ${entry.event} ${entry.method || ""} ${entry.path || ""} ${entry.status_code || ""} ${entry.error_type || ""}`
          ).join("\n")}</pre>
        )}
      </SettingsSection>

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
