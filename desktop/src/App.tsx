import { FormEvent, Fragment, isValidElement, useCallback, useEffect, useMemo, useState } from "react";
import type React from "react";
import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { getVersion } from "@tauri-apps/api/app";
import { check } from "@tauri-apps/plugin-updater";

import {
  AiProvider, AnalysisContentType, AnalysisMode, AnalysisPerformance, AnalysisResultHistory, ApiClient, Channel, ClientInquiryResponse, EgxCatalogStatus, ModelRetryAudit,
  DiagnosticEntry, SettingsInput, SettingsStatus, TelegramChat,
  StockSourceRow, StockSourceTableRow, StockSummaryRow,
} from "./api";

type Page = "Channels" | "Results" | "Settings";
type ThemeMode = "light" | "dark";
type Toast = { kind: "success" | "warning"; text: string } | null;
type AnalysisRunState = { running: boolean; progress: string };
type ChannelAnalysisConfig = {
  selectedHandles: string[];
  contentTypes: AnalysisContentType[];
  mode: AnalysisMode;
  targetDate: string;
};
type UpdateCandidate = {
  version: string;
  body?: string | null;
  downloadAndInstall: (onEvent: (event: { event: string; data: { contentLength?: number; chunkLength?: number } }) => void) => Promise<void>;
};

const pages: Page[] = ["Channels", "Results", "Settings"];
type IconName = "channels" | "results" | "settings" | "refresh" | "copy" | "check" | "plus" | "download" | "users" | "clear" | "play" | "eye" | "trash" | "image";

const PAGE_ICONS: Record<Page, IconName> = {
  Channels: "channels",
  Results: "results",
  Settings: "settings",
};

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.9, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  const paths = (() => {
    switch (name) {
      case "channels": return <><path {...common} d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle {...common} cx="9" cy="7" r="4" /><path {...common} d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" /></>;
      case "results": return <><path {...common} d="M4 19V5M4 19h16" /><path {...common} d="m7 15 4-4 3 2 5-6" /><path {...common} d="M16 7h3v3" /></>;
      case "settings": return <><circle {...common} cx="12" cy="12" r="3" /><path {...common} d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.1 2.1-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.03 1.56V20.3h-3v-.1A1.7 1.7 0 0 0 10.7 18.64a1.7 1.7 0 0 0-1.88.34l-.06.06-2.1-2.1.06-.06A1.7 1.7 0 0 0 7.06 15a1.7 1.7 0 0 0-1.56-1.03h-.1v-3h.1A1.7 1.7 0 0 0 7.06 9.94a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.1-2.1.06.06a1.7 1.7 0 0 0 1.88.34 1.7 1.7 0 0 0 1.03-1.56v-.1h3v.1a1.7 1.7 0 0 0 1.03 1.56 1.7 1.7 0 0 0 1.88-.34l.06-.06 2.1 2.1-.06.06a1.7 1.7 0 0 0-.34 1.88 1.7 1.7 0 0 0 1.56 1.03h.1v3H21a1.7 1.7 0 0 0-1.6 1.03Z" /></>;
      case "refresh": return <><path {...common} d="M20 11a8.2 8.2 0 0 0-15.5-2L3 11" /><path {...common} d="M3 5v6h6" /><path {...common} d="M4 13a8.2 8.2 0 0 0 15.5 2L21 13" /><path {...common} d="M21 19v-6h-6" /></>;
      case "copy": return <><rect {...common} x="9" y="9" width="11" height="11" rx="2" /><path {...common} d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h3" /></>;
      case "check": return <path {...common} d="m5 12 4 4L19 6" />;
      case "plus": return <><path {...common} d="M12 5v14M5 12h14" /></>;
      case "download": return <><path {...common} d="M12 3v12" /><path {...common} d="m7 10 5 5 5-5" /><path {...common} d="M5 21h14" /></>;
      case "users": return <><path {...common} d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle {...common} cx="9" cy="7" r="4" /></>;
      case "clear": return <><path {...common} d="M6 6l12 12M18 6 6 18" /></>;
      case "play": return <path {...common} d="m8 5 11 7-11 7V5Z" />;
      case "eye": return <><path {...common} d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" /><circle {...common} cx="12" cy="12" r="2.5" /></>;
      case "trash": return <><path {...common} d="M4 7h16M10 11v6M14 11v6M6 7l1 14h10l1-14M9 7V4h6v3" /></>;
      case "image": return <><rect {...common} x="3" y="4" width="18" height="16" rx="2" /><circle {...common} cx="8.5" cy="9" r="1.5" /><path {...common} d="m21 15-5-5L5 20" /></>;
    }
  })();
  return <svg className="icon" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">{paths}</svg>;
}

function normalizeChannelHandle(value: string): string {
  return value.trim().replace(/^@/, "").toLocaleLowerCase();
}

function loadChannelAnalysisConfig(): ChannelAnalysisConfig {
  try {
    return {
      selectedHandles: JSON.parse(sessionStorage.getItem("egx.selectedTelegramChats") || "[]") as string[],
      contentTypes: JSON.parse(sessionStorage.getItem("egx.analysisContentTypes") || '["text","images","audio"]') as AnalysisContentType[],
      mode: (sessionStorage.getItem("egx.analysisMode") as AnalysisMode | null) || "next_day",
      targetDate: sessionStorage.getItem("egx.analysisTargetDate") || "",
    };
  } catch {
    return { selectedHandles: [], contentTypes: ["text", "images", "audio"], mode: "next_day", targetDate: "" };
  }
}

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
            <Icon name={copied ? "check" : "copy"} /> {copied ? "Copied" : "Copy Message"}
          </button>
          <button type="button" onClick={onClose}><Icon name="check" /> OK</button>
        </div>
      </div>
    </div>
  );
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const [themeMode, setThemeMode] = useState<ThemeMode>(loadThemeMode);
  const [connected, setConnected] = useState(false);
  const [page, setPage] = useState<Page>("Channels");
  const [channels, setChannels] = useState<Channel[]>([]);
  const [analysisResults, setAnalysisResults] = useState<AnalysisResultHistory[]>([]);
  const [analysisRun, setAnalysisRun] = useState<AnalysisRunState>({ running: false, progress: "" });
  const [analysisConfig, setAnalysisConfig] = useState<ChannelAnalysisConfig>(loadChannelAnalysisConfig);
  const [settings, setSettings] = useState<SettingsStatus | null>(null);
  const [engineStarting, setEngineStarting] = useState(true);
  const [toast, setToast] = useState<Toast>(null);
  const [errorModal, setErrorModal] = useState<string | null>(null);
  const [successModal, setSuccessModal] = useState<string | null>(null);
  const [availableUpdate, setAvailableUpdate] = useState<UpdateCandidate | null>(null);
  const [checkingUpdate, setCheckingUpdate] = useState(false);
  const [downloadingUpdate, setDownloadingUpdate] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState<number | null>(null);
  const api = useMemo(() => new ApiClient(), []);

  useEffect(() => {
    document.documentElement.dataset.theme = themeMode;
    localStorage.setItem("egx.theme", themeMode);
  }, [themeMode]);

  const notify = (kind: "success" | "warning", text: string) => setToast({ kind, text });

  const showError = useCallback((fullText: string) => {
    setErrorModal(fullText);
    const short = fullText.length > 120 ? `${fullText.slice(0, 117)}…` : fullText;
    setToast({ kind: "warning", text: short });
  }, []);
  const showSuccess = useCallback((message: string) => setSuccessModal(message), []);

  const updateAnalysisConfig = useCallback((updater: (current: ChannelAnalysisConfig) => ChannelAnalysisConfig) => {
    setAnalysisConfig((current) => {
      const next = updater(current);
      sessionStorage.setItem("egx.selectedTelegramChats", JSON.stringify(next.selectedHandles));
      sessionStorage.setItem("egx.analysisContentTypes", JSON.stringify(next.contentTypes));
      sessionStorage.setItem("egx.analysisMode", next.mode);
      sessionStorage.setItem("egx.analysisTargetDate", next.targetDate);
      return next;
    });
  }, []);

  const refresh = async (showFailure = true): Promise<boolean> => {
    try {
      const [nextChannels, nextSettings] = await Promise.all([
        api.channels(), api.settings(),
      ]);
      setChannels(nextChannels);
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

  const runAnalysis = useCallback((channelIds: number[]) => {
    if (analysisRun.running) return;
    setAnalysisRun({ running: true, progress: "Collecting selected chat data..." });
    const progressTimers = [
      window.setTimeout(() => setAnalysisRun({ running: true, progress: "Preparing selected text, images, and audio..." }), 1_500),
      window.setTimeout(() => setAnalysisRun({ running: true, progress: "Analyzing selected content with the AI model..." }), 5_000),
      window.setTimeout(() => setAnalysisRun({ running: true, progress: "Saving the analysis result..." }), 20_000),
    ];
    void api.analyzeSelected(
      channelIds,
      analysisConfig.contentTypes,
      analysisConfig.mode,
      analysisConfig.mode === "specific_date" ? analysisConfig.targetDate : undefined,
    )
      .then(async (result) => {
        await refresh(false);
        setAnalysisResults(await api.analysisResults());
        const noStockContext = result.not_stock_related.length
          ? ` No stock-related context: ${result.not_stock_related.join(", ")}.`
          : "";
        showSuccess(
          `${result.messages_analyzed} of ${result.messages_in_window} messages were analyzed. ` +
          `Target suggestion date: ${result.target_date}. Inputs sent: ${contentTypeLabel(result.content_types)}. ` +
          `The result is now available in Results.${noStockContext}`,
        );
      })
      .catch((reason) => showError(fullError(reason)))
      .finally(() => {
        progressTimers.forEach((timer) => window.clearTimeout(timer));
        setAnalysisRun({ running: false, progress: "" });
      });
  }, [analysisConfig, analysisRun.running, api, refresh, showError, showSuccess]);

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
      notify("success", "Update installed. Restarting EGX Analyzer now.");
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
    if (connected && page === "Results") {
      void api.analysisResults().then(setAnalysisResults).catch((reason) => showError(fullError(reason)));
    }
  }, [api, connected, page, showError]);

  if (!connected) {
    return (
      <main className="login">
        <h1>EGX Analyzer</h1>
        <p>{engineStarting ? "Starting your local intelligence workspace…" : "Restarting the local intelligence workspace…"}</p>
        <span>Waiting for the local engine to become ready.</span>
      </main>
    );
  }

  return (
    <>
      <main className="shell">
        <aside>
          <h1>EGX Analyzer</h1>
          {pages.map((item) => (
            <button className={page === item ? "active" : ""} onClick={() => setPage(item)} key={item}>
              <Icon name={PAGE_ICONS[item]} /><span>{item}</span>
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
              {analysisRun.running && <span className="analysis-running-chip"><span /> Analysis running</span>}
              <button className="secondary" onClick={() => void refresh()}><Icon name="refresh" /> Refresh</button>
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

          {page === "Channels" && (
            <Channels
              channels={channels}
              api={api}
              refresh={refresh}
              notify={notify}
              showError={showError}
              analysisRun={analysisRun}
              analysisConfig={analysisConfig}
              updateAnalysisConfig={updateAnalysisConfig}
              onAnalyze={runAnalysis}
            />
          )}
          {page === "Results" && (
            <Results
              api={api}
              notify={notify}
              showError={showError}
              analysisResults={analysisResults}
              onAnalysisDeleted={(id) => setAnalysisResults((current) => current.filter((item) => item.id !== id))}
            />
          )}
          {page === "Settings" && (
            <CloudSettings
              api={api}
              status={settings}
              onSaved={refresh}
              onRunTelegramCheck={refresh}
              notify={notify}
              showError={showError}
              checkingUpdate={checkingUpdate}
              onCheckForUpdates={() => void checkForUpdates(true)}
              themeMode={themeMode}
              onThemeModeChange={setThemeMode}
            />
          )}
        </section>
      </main>

      {errorModal && <ErrorModal message={errorModal} onClose={() => setErrorModal(null)} />}
      {successModal && <SuccessModal message={successModal} onClose={() => setSuccessModal(null)} />}

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
type ShowSuccess = (message: string) => void;

const CONTENT_TYPE_LABEL: Record<AnalysisContentType, string> = {
  text: "Text messages",
  images: "Images / photos",
  audio: "Audio transcripts",
};

function contentTypeLabel(contentTypes: AnalysisContentType[]): string {
  return contentTypes.map((item) => CONTENT_TYPE_LABEL[item]).join(", ");
}

function cairoDateInputValue(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Africa/Cairo", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date());
  const value = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${value("year")}-${value("month")}-${value("day")}`;
}

// ── Reports ───────────────────────────────────────────────────────────────────

function Reports({ api, rows, setRows, notify, showError }: {
  api: ApiClient; rows: Array<Record<string, unknown>>;
  setRows: (rows: Array<Record<string, unknown>>) => void;
  notify: Notify; showError: ShowError;
}) {
  const [mode, setMode] = useState<"calendar" | "session">("calendar");
  const [generating, setGenerating] = useState(false);
  const [openTableId, setOpenTableId] = useState<number | null>(null);
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
    markdown_path?: string; html_path?: string;
    summary?: {
      original_ai_response_text_path?: string;
      stock_source_table?: StockSourceTableRow[];
    };
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
            {(report.summary?.stock_source_table?.length ?? 0) > 0 && (
              <button className="secondary compact" onClick={() => setOpenTableId((current) => current === report.id ? null : report.id ?? null)}>
                {openTableId === report.id ? "Hide table" : "View table in app"}
              </button>
            )}
            {report.html_path && (
              <a href={`file:///${String(report.html_path).replace(/\\/g, "/")}`}
                target="_blank" rel="noreferrer" className="report-link">
                HTML report
              </a>
            )}
            {report.summary?.original_ai_response_text_path && (
              <a href={`file:///${String(report.summary.original_ai_response_text_path).replace(/\\/g, "/")}`}
                target="_blank" rel="noreferrer" className="report-link muted">
                AI response text
              </a>
            )}
          </div>
          {openTableId === report.id && report.summary?.stock_source_table && (
            <ConsolidatedStockTable rows={report.summary.stock_source_table} />
          )}
        </div>
      ))}
    </>
  );
}

// ── Channels ──────────────────────────────────────────────────────────────────

function Channels({ channels, api, refresh, notify, showError, analysisRun, analysisConfig, updateAnalysisConfig, onAnalyze }: {
  channels: Channel[]; api: ApiClient;
  refresh: () => Promise<boolean>; notify: Notify; showError: ShowError;
  analysisRun: AnalysisRunState; analysisConfig: ChannelAnalysisConfig;
  updateAnalysisConfig: (updater: (current: ChannelAnalysisConfig) => ChannelAnalysisConfig) => void;
  onAnalyze: (channelIds: number[]) => void;
}) {
  const [handle, setHandle] = useState("");
  const [chatQuery, setChatQuery] = useState("");
  const [chats, setChats] = useState<TelegramChat[]>(() => {
    try { return JSON.parse(sessionStorage.getItem("egx.telegramChats") || "[]") as TelegramChat[]; }
    catch { return []; }
  });
  const [loading, setLoading] = useState(false);
  const latestHistoricalDate = useMemo(cairoDateInputValue, []);
  const { selectedHandles, contentTypes, mode: analysisMode, targetDate } = analysisConfig;
  const busy = loading || analysisRun.running;
  const analyzing = analysisRun.running;
  const analysisProgress = analysisRun.progress;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    void api.addChannel(handle)
      .then((channel) => {
        updateSelectedHandles([...new Set([...selectedHandles, channel.handle])]);
        setHandle("");
        return refresh();
      })
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
    updateAnalysisConfig((current) => ({
      ...current,
      selectedHandles: [...new Set(handles.map(normalizeChannelHandle).filter(Boolean))],
    }));
  };

  const addChat = (chat: TelegramChat) => {
    setLoading(true);
    void api.selectTelegramChat(chat)
      .then((channel) => {
        updateAnalysisConfig((current) => ({
          ...current,
          selectedHandles: [...new Set([...current.selectedHandles, channel.handle].map(normalizeChannelHandle).filter(Boolean))],
        }));
        return refresh();
      })
      .then(() => notify("success", `${chat.title} is selected for this session.`))
      .catch((reason) => showError(fullError(reason)))
      .finally(() => setLoading(false));
  };

  const removeChat = (h: string) => {
    const selectedHandle = normalizeChannelHandle(h);
    updateAnalysisConfig((current) => ({
      ...current,
      selectedHandles: current.selectedHandles.filter((item) => normalizeChannelHandle(item) !== selectedHandle),
    }));
    notify("success", "Chat removed from this session.");
  };

  const selectVisibleChats = () => {
    const toSelect = visibleChats.filter((chat) => !selected.has(chatHandle(chat)));
    if (!toSelect.length) return;
    setLoading(true);
    void Promise.all(toSelect.map((chat) => api.selectTelegramChat(chat)))
      .then((selectedChannels) => {
        updateAnalysisConfig((current) => ({
          ...current,
          selectedHandles: [...new Set([...current.selectedHandles, ...selectedChannels.map((channel) => channel.handle)].map(normalizeChannelHandle).filter(Boolean))],
        }));
        return refresh();
      })
      .then(() => notify("success", `${toSelect.length} visible chats selected for this session.`))
      .catch((reason) => showError(fullError(reason)))
      .finally(() => setLoading(false));
  };

  const selected = new Set(selectedHandles.map(normalizeChannelHandle));
  const selectedChannels = channels.filter((channel) => selected.has(normalizeChannelHandle(channel.handle)));

  const chatHandle = (chat: TelegramChat) => {
    if (chat.username) return normalizeChannelHandle(chat.username);
    const raw = chat.id.replace(/^-/, "");
    return normalizeChannelHandle(raw.startsWith("100") ? raw.slice(3) : raw);
  };
  const visibleChats = chats
    .filter((chat) => `${chat.title} ${chat.username} ${chat.kind}`.toLocaleLowerCase().includes(chatQuery.trim().toLocaleLowerCase()))
    .sort((left, right) => Number(selected.has(chatHandle(right))) - Number(selected.has(chatHandle(left))) || left.title.localeCompare(right.title));

  const toggleContentType = (contentType: AnalysisContentType) => {
    updateAnalysisConfig((current) => ({
      ...current,
      contentTypes: current.contentTypes.includes(contentType)
        ? current.contentTypes.filter((item) => item !== contentType)
        : [...current.contentTypes, contentType],
    }));
  };

  const analyze = () => {
    const ids = selectedChannels.map((channel) => channel.id);
    if (!ids.length) return notify("warning", "Select at least one chat first.");
    if (!contentTypes.length) return notify("warning", "Choose at least one input type to analyze.");
    if (analysisMode === "specific_date" && !targetDate) return notify("warning", "Choose the target date to analyze.");
    onAnalyze(ids);
  };

  const toggleChatSelection = (chat: TelegramChat) => {
    if (busy) return;
    const chatId = chatHandle(chat);
    if (selected.has(chatId)) removeChat(chatId);
    else addChat(chat);
  };

  const handleChatRowKeyDown = (event: React.KeyboardEvent<HTMLTableRowElement>, chat: TelegramChat) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    toggleChatSelection(chat);
  };

  return (
    <>
      <div className="channels-section channel-picker-section">
        <h3 className="section-heading">1. Choose chats for this session</h3>
        <p className="section-description">Load your Telegram chats, then select only the sources you want to analyze.</p>
        <details className="manual-channel-add">
          <summary>Add a chat manually</summary>
          <form className="inline" onSubmit={submit}>
            <input value={handle} onChange={(e) => setHandle(e.target.value)} placeholder="Telegram username, without @" required />
            <button disabled={busy}><Icon name="plus" /> Add channel</button>
          </form>
        </details>
        <button className="secondary load-chats-button" onClick={loadChats} disabled={busy}>
          <Icon name="download" /> {loading ? "Loading chats…" : "Load my Telegram chats"}
        </button>
        {chats.length > 0 && <>
          <div className="channel-list-toolbar">
            <input value={chatQuery} onChange={(event) => setChatQuery(event.target.value)} placeholder="Filter chats by name, username, or type" />
            <span>{selectedChannels.length} selected</span>
            <button type="button" className="secondary compact" disabled={busy || !visibleChats.some((chat) => !selected.has(chatHandle(chat)))} onClick={selectVisibleChats}><Icon name="users" size={16} /> Select visible</button>
            <button type="button" className="secondary compact" disabled={!selectedChannels.length || busy} onClick={() => updateSelectedHandles([])}><Icon name="clear" size={16} /> Clear selection</button>
          </div>
          <div className="table channel-chat-table">
            <table>
              <thead><tr><th>Chat</th><th>Type</th><th>Selection</th></tr></thead>
              <tbody>{visibleChats.map((chat) => {
                const isSelected = selected.has(chatHandle(chat));
                return (
                  <tr
                    key={chat.id}
                    className={isSelected ? "channel-chat-row is-selected" : "channel-chat-row"}
                    role="button"
                    tabIndex={busy ? -1 : 0}
                    aria-pressed={isSelected}
                    onClick={() => toggleChatSelection(chat)}
                    onKeyDown={(event) => handleChatRowKeyDown(event, chat)}
                  >
                    <td><strong>{chat.title}</strong>{chat.username && <span className="channel-chat-username">@{chat.username}</span>}</td>
                    <td>{chat.kind}</td>
                    <td><span className={isSelected ? "channel-selection-state selected" : "channel-selection-state"}>{isSelected ? "Selected" : "Select"}</span></td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
        </>}
      </div>

      <div className="channels-section analysis-setup-section">
        <h3 className="section-heading">2. Configure and analyze ({selectedChannels.length} selected)</h3>
        <div className="analysis-window-note">
          <strong>{analysisMode === "next_day" ? "Automatic next-day analysis" : "Historical target-date analysis"}</strong>
          <p>{analysisMode === "next_day"
            ? "Uses selected-chat messages, images, and available audio from yesterday at 00:00 Cairo time through the moment you press Analyze. The model keeps only suggestions intended for the next day based on dates and context inside the content."
            : "Uses selected-chat content from the prior Cairo day at 00:00 through 23:59 on the selected date. The model keeps only suggestions explicitly intended for the selected date."}</p>
        </div>
        <fieldset className="analysis-date-mode" disabled={busy}>
          <legend>Recommendation target date</legend>
          <label><input type="radio" name="analysis-mode" checked={analysisMode === "next_day"} onChange={() => updateAnalysisConfig((current) => ({ ...current, mode: "next_day" }))} /> Next day (default)</label>
          <label><input type="radio" name="analysis-mode" checked={analysisMode === "specific_date"} onChange={() => updateAnalysisConfig((current) => ({ ...current, mode: "specific_date" }))} /> Choose a historical date</label>
          {analysisMode === "specific_date" && (
            <label className="analysis-date-picker">Target date
              <input type="date" max={latestHistoricalDate} value={targetDate} onChange={(event) => updateAnalysisConfig((current) => ({ ...current, targetDate: event.target.value }))} required />
            </label>
          )}
        </fieldset>
        <fieldset className="analysis-content-types" disabled={busy}>
          <legend>Send to the model</legend>
          {(Object.keys(CONTENT_TYPE_LABEL) as AnalysisContentType[]).map((contentType) => (
            <label key={contentType}>
              <input
                type="checkbox"
                checked={contentTypes.includes(contentType)}
                onChange={() => toggleContentType(contentType)}
              />
              {CONTENT_TYPE_LABEL[contentType]}
            </label>
          ))}
        </fieldset>
        <button onClick={analyze} disabled={busy}>
          <Icon name="play" /> {analyzing ? "Analyzing selected chats…" : "Analyze selected chats"}
        </button>
        {analyzing && <p className="analysis-progress" role="status">{analysisProgress}</p>}
      </div>
    </>
  );
}

// ── Results (merged Recommendations + Search) ─────────────────────────────────

function Results({ api, notify, showError, analysisResults, onAnalysisDeleted }: {
  api: ApiClient;
  notify: Notify; showError: ShowError; analysisResults: AnalysisResultHistory[];
  onAnalysisDeleted: (id: number) => void;
}) {
  return (
    <AnalysisResultHistoryTable items={analysisResults} api={api} notify={notify} showError={showError} onDeleted={onAnalysisDeleted} />
  );
}

function formatGeneratedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function normalizeStockSearch(value: string): string {
  return value
    .toLocaleLowerCase()
    .normalize("NFKD")
    .replace(/[\u064B-\u065F\u0670]/g, "")
    .replace(/[أإآ]/g, "ا")
    .replace(/ى/g, "ي")
    .replace(/ة/g, "ه")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

function editDistance(left: string, right: string): number {
  const previous = Array.from({ length: right.length + 1 }, (_, index) => index);
  for (let leftIndex = 1; leftIndex <= left.length; leftIndex += 1) {
    let diagonal = previous[0];
    previous[0] = leftIndex;
    for (let rightIndex = 1; rightIndex <= right.length; rightIndex += 1) {
      const above = previous[rightIndex];
      previous[rightIndex] = Math.min(
        previous[rightIndex] + 1,
        previous[rightIndex - 1] + 1,
        diagonal + (left[leftIndex - 1] === right[rightIndex - 1] ? 0 : 1),
      );
      diagonal = above;
    }
  }
  return previous[right.length];
}

function matchesStockQuery(row: StockSourceTableRow, query: string): boolean {
  const normalizedQuery = normalizeStockSearch(query);
  if (!normalizedQuery) return true;
  const candidates = [row.ticker, row.company, row.company_ar || ""]
    .flatMap((value) => [normalizeStockSearch(value), ...normalizeStockSearch(value).split(" ")])
    .filter(Boolean);
  const allowedDistance = normalizedQuery.length >= 6 ? 2 : 1;
  return candidates.some((candidate) => candidate.includes(normalizedQuery) || editDistance(candidate, normalizedQuery) <= allowedDistance);
}

function loadThemeMode(): ThemeMode {
  return localStorage.getItem("egx.theme") === "light" ? "light" : "dark";
}

function formatDuration(milliseconds: number | undefined): string {
  if (!milliseconds || milliseconds < 1_000) return `${milliseconds ?? 0} ms`;
  const seconds = milliseconds / 1_000;
  return seconds >= 60 ? `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s` : `${seconds.toFixed(seconds >= 10 ? 0 : 1)}s`;
}

function AnalysisPerformancePanel({ performance }: { performance: AnalysisPerformance }) {
  if (!Object.keys(performance).length) return null;
  const modelDuration = performance.model_requests_total_ms ?? performance.model_request_ms ?? performance.model_pipeline_ms;
  const totalDuration = performance.total_analysis_ms ?? performance.total_before_commit_ms;
  const calls = performance.model_request_count ?? 1;
  const stages = [
    ["Telegram collection", performance.telegram_collection_ms],
    ["Model preparation", performance.image_preparation_ms],
    ["AI provider", modelDuration],
    ["Catalog", performance.catalog_enrichment_ms],
    ["Save results", performance.report_generation_ms],
  ].filter(([, duration]) => typeof duration === "number") as Array<[string, number]>;
  const slowest = stages.reduce<[string, number] | null>((current, stage) => !current || stage[1] > current[1] ? stage : current, null);
  return <section className="analysis-performance" aria-label="Analysis timing">
    <div><strong>Analysis timing</strong><span>Total: {formatDuration(totalDuration)}</span></div>
    <p>{calls > 1 ? `${calls} AI requests were made, including an automatic validation retry. ` : "One AI request was made. "}
      {slowest ? `Longest stage: ${slowest[0]} (${formatDuration(slowest[1])}).` : ""}</p>
    <div className="analysis-performance-stages">
      {stages.map(([label, duration]) => <span key={label}>{label}<strong>{formatDuration(duration)}</strong></span>)}
    </div>
  </section>;
}

function ModelRetryAuditPanel({ audit }: { audit: ModelRetryAudit }) {
  if (!audit.attempted) return null;
  const passed = audit.status === "passed";
  const triggers = audit.trigger_warnings?.length ?? 0;
  const remaining = audit.final_validation_warnings?.length ?? 0;
  return <div className={`model-retry-audit ${passed ? "passed" : "warning"}`}>
    <strong>{passed ? "Automatic retry passed validation" : "Automatic retry completed with warnings"}</strong>
    <span>Triggered by {triggers} validation issue{triggers === 1 ? "" : "s"}; {remaining ? `${remaining} remain.` : "none remain."}</span>
  </div>;
}

function AnalysisResultHistoryTable({ items, api, notify, showError, onDeleted }: {
  items: AnalysisResultHistory[]; api: ApiClient; notify: Notify; showError: ShowError; onDeleted: (id: number) => void;
}) {
  const [expandedAnalysis, setExpandedAnalysis] = useState<number | null>(null);
  const [expandedSection, setExpandedSection] = useState<"recommendations" | "inquiries" | null>(null);
  const [stockQuery, setStockQuery] = useState("");
  const [deleteCandidate, setDeleteCandidate] = useState<AnalysisResultHistory | null>(null);
  const [deleting, setDeleting] = useState(false);
  if (!items.length) return <div className="results-empty-state">
    <strong>No saved analysis results</strong>
    <span>Run an analysis from Channels. Each completed run will appear here with its recommendations and client inquiry replies.</span>
  </div>;

  const confirmDelete = () => {
    if (!deleteCandidate) return;
    setDeleting(true);
    void api.deleteAnalysisResult(deleteCandidate.id)
      .then(() => {
        if (expandedAnalysis === deleteCandidate.id) {
          setExpandedAnalysis(null);
          setExpandedSection(null);
        }
        onDeleted(deleteCandidate.id);
        setDeleteCandidate(null);
        notify("success", "Analysis result and its generated files were deleted.");
      })
      .catch((reason) => showError(fullError(reason)))
      .finally(() => setDeleting(false));
  };

  const toggleAnalysis = (id: number) => {
    if (expandedAnalysis === id) {
      setExpandedAnalysis(null);
      setExpandedSection(null);
      return;
    }
    setExpandedAnalysis(id);
    setExpandedSection(null);
  };

  const toggleSection = (section: "recommendations" | "inquiries") => {
    setExpandedSection((current) => current === section ? null : section);
    if (section === "recommendations") setStockQuery("");
  };

  const totalRecommendationRows = items.reduce((total, item) => total + item.stock_source_table.length, 0);
  const totalInquiryReplies = items.reduce((total, item) => total + item.client_inquiry_responses.length, 0);

  return (
    <div className="analysis-history-wrap">
      <section className="results-overview" aria-label="Saved results overview">
        <div>
          <span className="results-eyebrow">Saved analysis</span>
          <h2>Results history</h2>
          <p>Open a run to review source-by-source recommendations or separate client inquiry replies.</p>
        </div>
        <div className="results-overview-stats">
          <span><strong>{items.length}</strong> runs</span>
          <span><strong>{totalRecommendationRows}</strong> recommendation rows</span>
          <span><strong>{totalInquiryReplies}</strong> inquiry replies</span>
        </div>
      </section>
      <table className="analysis-history-table">
        <colgroup>
          <col className="analysis-history-output-col" />
          <col className="analysis-history-date-col" />
          <col className="analysis-history-inputs-col" />
          <col className="analysis-history-scope-col" />
          <col className="analysis-history-records-col" />
          <col className="analysis-history-actions-col" />
        </colgroup>
        <thead>
          <tr><th>Generated output</th><th>Target date</th><th>Inputs sent</th><th>Scope</th><th>Records</th><th className="analysis-history-actions-heading">Actions</th></tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const analysisOpen = expandedAnalysis === item.id;
            const recommendationsOpen = analysisOpen && expandedSection === "recommendations";
            const inquiriesOpen = analysisOpen && expandedSection === "inquiries";
            const stockCount = new Set(item.stock_source_table.map((row) => row.ticker)).size;
            return (
              <Fragment key={item.id}>
                <tr className="analysis-history-row" onClick={() => toggleAnalysis(item.id)}>
                  <td><strong>Analysis · {formatGeneratedAt(item.generated_at)}</strong></td>
                  <td>{item.target_date || "—"}</td>
                  <td>{contentTypeLabel(item.content_types)}</td>
                  <td>{item.messages_analyzed} messages</td>
                  <td>{stockCount} stocks / {item.stock_source_table.length} source rows</td>
                  <td className="analysis-history-actions">
                    <div className="analysis-history-action-buttons">
                      <button type="button" className="secondary compact" onClick={(event) => {
                        event.stopPropagation();
                        toggleAnalysis(item.id);
                      }}><Icon name={analysisOpen ? "clear" : "eye"} size={16} /> {analysisOpen ? "Hide" : "View"}</button>
                      <button type="button" className="danger compact" onClick={(event) => {
                        event.stopPropagation();
                        setDeleteCandidate(item);
                      }}><Icon name="trash" size={16} /> Delete</button>
                    </div>
                  </td>
                </tr>
                {analysisOpen && (
                  <tr className="analysis-history-expanded">
                    <td colSpan={6}>
                      <div className="analysis-expanded-header">
                        <div>
                          <span className="results-eyebrow">Analysis run</span>
                          <strong>{formatGeneratedAt(item.generated_at)}</strong>
                        </div>
                        <div className="analysis-expanded-meta">
                          <span>Target: <strong>{item.target_date || "—"}</strong></span>
                          <span>Inputs: <strong>{contentTypeLabel(item.content_types)}</strong></span>
                        </div>
                      </div>
                      <div className="analysis-section-list">
                        <AnalysisPerformancePanel performance={item.performance} />
                        <ModelRetryAuditPanel audit={item.model_retry_audit} />
                        {!!item.model_validation_warnings.length && <div className="analysis-result-warning">
                          <strong>Model output warning</strong>
                          <span>{item.model_correction_attempted ? "An automatic correction was attempted. " : ""}{item.model_validation_warnings.join(" ")}</span>
                        </div>}
                        <button type="button" className="analysis-section-row" onClick={() => toggleSection("recommendations")} aria-expanded={recommendationsOpen}>
                          <span><strong>Recommendations table</strong><small>One model-returned row for each dated source recommendation</small></span>
                          <span>{item.stock_source_table.length} rows - {recommendationsOpen ? "Hide" : "View"}</span>
                        </button>
                        {recommendationsOpen && <div className="analysis-section-content">
                      <label className="analysis-result-search">
                        Find stock code or name
                        <input
                          value={stockQuery}
                          onChange={(event) => setStockQuery(event.target.value)}
                          placeholder="COMI, Commercial International Bank, البنك التجاري…"
                        />
                      </label>
                      <ConsolidatedStockTable rows={item.stock_source_table.filter((row) => matchesStockQuery(row, stockQuery))} />
                        </div>}
                        <button type="button" className="analysis-section-row analysis-section-reference" onClick={() => toggleSection("inquiries")} aria-expanded={inquiriesOpen}>
                          <span><strong>Client inquiry replies</strong><small>Reference-only replies, excluded from recommendations</small></span>
                          <span>{item.client_inquiry_responses.length} replies - {inquiriesOpen ? "Hide" : "View"}</span>
                        </button>
                        {inquiriesOpen && <div className="analysis-section-content"><ClientInquiryResponses rows={item.client_inquiry_responses} /></div>}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      {deleteCandidate && (
        <DeleteAnalysisResultModal
          item={deleteCandidate}
          deleting={deleting}
          onCancel={() => setDeleteCandidate(null)}
          onConfirm={confirmDelete}
        />
      )}
    </div>
  );
}

function DeleteAnalysisResultModal({ item, deleting, onCancel, onConfirm }: {
  item: AnalysisResultHistory; deleting: boolean; onCancel: () => void; onConfirm: () => void;
}) {
  return (
    <div className="error-modal-backdrop" role="dialog" aria-modal="true" aria-label="Delete analysis result">
      <div className="error-modal-card delete-modal-card">
        <h2 className="error-modal-title delete-modal-title">Delete analysis result?</h2>
        <p className="success-modal-body">
          Delete the result generated on {formatGeneratedAt(item.generated_at)}? This permanently removes its table, reports, AI response files, and saved trace.
        </p>
        <div className="error-modal-actions">
          <button type="button" className="secondary" onClick={onCancel} disabled={deleting}>Cancel</button>
          <button type="button" className="danger" onClick={onConfirm} disabled={deleting}>{deleting ? "Deleting…" : "Delete permanently"}</button>
        </div>
      </div>
    </div>
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

function num(v: unknown): string {
  if (v === undefined || v === null || v === "" || v === "None" || v === "null") return "—";
  const n = Number(v);
  return Number.isNaN(n) ? String(v) : String(n);
}

function dateBasisLabel(basis: string): string {
  const labels: Record<string, string> = {
    explicit_date: "Explicit date",
    t_plus_1: "T+1",
    next_session: "Next session",
    tomorrow: "Tomorrow",
  };
  return labels[basis] ?? basis;
}

function SuccessModal({ message, onClose }: { message: string; onClose: () => void }) {
  return (
    <div className="error-modal-backdrop" role="dialog" aria-modal="true" aria-label="Analysis completed">
      <div className="error-modal-card success-modal-card">
        <h2 className="error-modal-title success-modal-title">Analysis completed</h2>
        <p className="success-modal-body">{message}</p>
        <div className="error-modal-actions">
          <button type="button" onClick={onClose}>OK</button>
        </div>
      </div>
    </div>
  );
}

function ConsolidatedStockTable({ rows }: { rows: StockSourceTableRow[] }) {
  const [sourceImages, setSourceImages] = useState<{ paths: string[]; title: string } | null>(null);
  const grouped = new Map<string, StockSourceTableRow[]>();
  rows.forEach((row) => {
    const group = grouped.get(row.ticker) ?? [];
    group.push(row);
    grouped.set(row.ticker, group);
  });
  if (!rows.length) return <p className="empty">No structured EGX recommendations were found.</p>;

  return (
    <div className="consolidated-table-wrap">
      <div className="consolidated-table-title">
        <strong>EGX recommendations by source</strong>
        <span>Each row preserves one model-returned dated recommendation without combining source values.</span>
      </div>
      <div className="consolidated-table-scroll">
        <table className="consolidated-table">
          <thead><tr>
            <th>Source</th><th>Date</th><th>Timing</th><th>Type</th><th>Entry</th><th>TP1</th><th>TP2</th>
            <th>Stop</th><th>Support</th><th>Resistance</th><th>Return %</th><th>Risk %</th><th>Status</th><th>Source image</th><th>Notes</th>
          </tr></thead>
          {[...grouped.entries()].map(([ticker, stockRows]) => {
            const first = stockRows[0];
            return (
              <tbody key={ticker}>
                <tr className="consolidated-stock-group"><td colSpan={15}>
                  <span className="consolidated-rank">#{first.rank ?? "—"}</span>
                  <strong>{first.ticker}</strong>
                  <span>{first.company}</span>
                  {first.company_ar && <span className="consolidated-company-ar">{first.company_ar}</span>}
                  <span className="consolidated-mentions">{first.mention_count} total mentions</span>
                </td></tr>
                {stockRows.map((row) => (
                  <tr key={`${row.ticker}-${row.source}-${row.latest_date ?? "unknown"}-${row.buy_price ?? "none"}`}>
                    <td className="source-cell">{row.source}</td>
                    <td>{row.source_dates.join(", ") || "—"}</td>
                    <td>{row.effective_date_bases?.length ? row.effective_date_bases.map((basis) => <span key={basis} className="recommendation-date-basis">{dateBasisLabel(basis)}</span>) : "—"}</td>
                    <td><span className={`status-pill ${row.recommendation_type === "sell" ? "neutral" : "active"}`}>{row.recommendation_type || "buy"}</span></td>
                    <td className="numeric">{num(row.buy_price)}</td>
                    <td className="numeric positive">{num(row.target_1)}</td>
                    <td className="numeric positive">{num(row.target_2)}</td>
                    <td className="numeric negative">{num(row.stop_loss)}</td>
                    <td className="numeric">{num(row.support)}</td>
                    <td className="numeric">{num(row.resistance)}</td>
                    <td className="numeric positive">{num(row.expected_return_pct)}</td>
                    <td className="numeric negative">{num(row.risk_pct)}</td>
                    <td><span className={`status-pill ${row.status === "active" ? "active" : "neutral"}`}>{row.status || "—"}</span></td>
                    <td className="source-image-cell">
                      {row.source_image_paths?.length ? <button type="button" className="secondary compact source-image-button" onClick={() => setSourceImages({ paths: row.source_image_paths ?? [], title: `${row.ticker} - ${row.source}` })}>
                        <Icon name="image" size={15} /> View ({row.source_image_paths.length})
                      </button> : "—"}
                    </td>
                    <td className="analysis-summary">{row.notes_ar || row.analysis_summary_ar || "—"}</td>
                  </tr>
                ))}
              </tbody>
            );
          })}
        </table>
      </div>
      {sourceImages && <SourceImageModal paths={sourceImages.paths} title={sourceImages.title} onClose={() => setSourceImages(null)} />}
    </div>
  );
}

function SourceImageModal({ paths, title, onClose }: { paths: string[]; title: string; onClose: () => void }) {
  const [index, setIndex] = useState(0);
  const currentPath = paths[index];
  return (
    <div className="error-modal-backdrop source-image-backdrop" role="dialog" aria-modal="true" aria-label={`Source image for ${title}`}>
      <div className="error-modal-card source-image-modal-card">
        <div className="source-image-modal-heading">
          <div><h2 className="error-modal-title source-image-modal-title">Source image</h2><p>{title}</p></div>
          {paths.length > 1 && <span>{index + 1} / {paths.length}</span>}
        </div>
        <img className="source-image-preview" src={convertFileSrc(currentPath)} alt={`Telegram source image for ${title}`} />
        <div className="error-modal-actions">
          {paths.length > 1 && <><button type="button" className="secondary" disabled={index === 0} onClick={() => setIndex((current) => current - 1)}>Previous</button><button type="button" className="secondary" disabled={index === paths.length - 1} onClick={() => setIndex((current) => current + 1)}>Next</button></>}
          <a className="secondary source-image-open" href={`file:///${currentPath.replace(/\\/g, "/")}`} target="_blank" rel="noreferrer">Open file</a>
          <button type="button" onClick={onClose}><Icon name="check" /> Close</button>
        </div>
      </div>
    </div>
  );
}

function ClientInquiryResponses({ rows }: { rows: ClientInquiryResponse[] }) {
  if (!rows.length) return <p className="empty">No client inquiry replies were found in this analysis.</p>;
  const groups = new Map<string, ClientInquiryResponse[]>();
  rows.forEach((row) => {
    const group = groups.get(row.ticker) ?? [];
    group.push(row);
    groups.set(row.ticker, group);
  });
  return (
    <section className="client-inquiries" aria-label="ردود استفسارات العملاء" dir="rtl">
      <div className="client-inquiries-heading">
        <strong>ردود استفسارات العملاء</strong>
        <span>للمرجع فقط — لا تدخل ضمن التوصيات</span>
      </div>
      {[...groups.entries()].map(([ticker, replies]) => {
        const first = replies[0];
        return (
          <section className="client-inquiry-group" key={ticker}>
            <h4><span dir="ltr">{ticker}</span> {first.company_ar || first.company}{first.company_ar ? ` / ${first.company}` : ""}</h4>
            <div className="client-inquiry-cards">
              {replies.map((row, index) => <ClientInquiryCard key={`${row.source}-${row.date ?? ""}-${row.source_message_id ?? index}`} row={row} />)}
            </div>
          </section>
        );
      })}
    </section>
  );
}

function ClientInquiryCard({ row }: { row: ClientInquiryResponse }) {
  const availableLevels = (levels: Array<[string, number | null | undefined]>) => levels
    .filter(([, value]) => value !== undefined && value !== null)
    .map(([label, value]) => [label, num(value)] as const);
  const tradeLevels = availableLevels([
    ["سعر الدخول", row.buy_price], ["الهدف الأول", row.target_1], ["الهدف الثاني", row.target_2], ["وقف الخسارة", row.stop_loss],
  ]);
  const marketLevels = availableLevels([
    ["آخر سعر", row.last_price], ["الدعم", row.support], ["المقاومة", row.resistance],
  ]);
  const assessment = row.reply_summary_ar || row.advice_ar;
  return (
    <article className="client-inquiry-card" dir="rtl">
      <header className="client-inquiry-card-header">
        <div className="client-inquiry-origin">
          <span className="client-inquiry-kind">رد على استفسار</span>
          <strong>{row.source}</strong>
          <span dir="ltr">{row.date || "بدون تاريخ"}</span>
        </div>
        {row.current_trend_ar && <span className="client-inquiry-trend">{row.current_trend_ar}</span>}
      </header>
      {(row.question_summary_ar || assessment) && <div className="client-inquiry-summary">
        {row.question_summary_ar && <p><span>استفسار العميل</span>{row.question_summary_ar}</p>}
        {assessment && <p><span>الرد والتحليل</span>{assessment}</p>}
      </div>}
      {tradeLevels.length > 0 && <dl className="client-inquiry-levels">
        {tradeLevels.map(([label, value]) => <div key={label}><dt>{label}</dt><dd dir="ltr">{value}</dd></div>)}
      </dl>}
      {marketLevels.length > 0 && <dl className="client-inquiry-market-levels">
        {marketLevels.map(([label, value]) => <div key={label}><dt>{label}</dt><dd dir="ltr">{value}</dd></div>)}
      </dl>}
      {(row.advice_ar || row.alternate_scenario_ar) && <div className="client-inquiry-guidance">
        {row.advice_ar && row.advice_ar !== assessment && <p><span>النصيحة</span>{row.advice_ar}</p>}
        {row.alternate_scenario_ar && <p className="client-inquiry-scenario"><span>السيناريو البديل</span>{row.alternate_scenario_ar}</p>}
      </div>}
    </article>
  );
}

function LegacyClientInquiryResponses({ rows }: { rows: ClientInquiryResponse[] }) {
  if (!rows.length) return null;
  return (
    <details className="client-inquiries">
      <summary>Client inquiry responses ({rows.length}) <span>Reference only — excluded from active recommendations</span></summary>
      <div className="consolidated-table-scroll">
        <table className="consolidated-table client-inquiry-table">
          <thead><tr><th>Stock</th><th>Source</th><th>Date</th><th>Customer inquiry</th><th>Reply / advice</th><th>Levels</th></tr></thead>
          <tbody>{rows.map((row, index) => (
            <tr key={`${row.ticker}-${row.source}-${row.date ?? ""}-${index}`}>
              <td><strong>{row.ticker}</strong><br /><span>{row.company}</span>{row.company_ar && <><br /><span className="consolidated-company-ar">{row.company_ar}</span></>}</td>
              <td>{row.source}</td><td>{row.date || "—"}</td>
              <td className="analysis-summary">{row.question_summary_ar || "—"}</td>
              <td className="analysis-summary">{row.reply_summary_ar || row.advice_ar || "—"}{row.alternate_scenario_ar && <><br /><small>Alternative: {row.alternate_scenario_ar}</small></>}</td>
              <td className="numeric">Last {num(row.last_price)}<br />Support {num(row.support)}<br />Resistance {num(row.resistance)}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </details>
  );
}

function AnalysisResultTable({ summary, details, sourceRows = [], channelResults, reportHtmlPath, aiResponseTextPath, tracePath }: {
  summary: StockSummaryRow[];
  details: StockSourceRow[];
  sourceRows: StockSourceTableRow[];
  channelResults: Array<{ channel: string; status: string; messages: number; recommendations: number; stock_codes: number }>;
  reportHtmlPath: string;
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

      {sourceRows.length > 0 && <ConsolidatedStockTable rows={sourceRows} />}

      {sourceRows.length === 0 && stocks.map((stock) => {
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
      if (announce) showError("Save settings for the selected provider first.");
      return;
    }
    setLoading(true);
    try {
      const loaded = await api.models();
      setModels(loaded);
      if (announce && loaded.length === 0) {
        showError("No models are available to this provider account.");
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
      <small className="model-selector-help">Shows every model currently available from the selected provider. Choose a vision-capable model when analyzing photos.</small>
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

function CloudSettings({ api, status, onSaved, onRunTelegramCheck, notify, showError, checkingUpdate, onCheckForUpdates, themeMode, onThemeModeChange }: {
  api: ApiClient; status: SettingsStatus | null; onSaved: () => Promise<boolean>;
  onRunTelegramCheck: () => Promise<boolean>;
  notify: Notify; showError: ShowError; checkingUpdate: boolean; onCheckForUpdates: () => void;
  themeMode: ThemeMode; onThemeModeChange: (theme: ThemeMode) => void;
}) {
  const [values, setValues] = useState<SettingsInput>({
    ai_provider: status?.ai_provider || "qwen",
    openai_model: status?.openai_model || "qwen3-vl-plus",
    ollama_model: status?.ollama_model || "qwen3-vl:4b",
    ollama_base_url: status?.ollama_base_url || "http://127.0.0.1:11434",
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
  const [checkingTelegram, setCheckingTelegram] = useState(false);
  const [diagnostics, setDiagnostics] = useState<DiagnosticEntry[]>([]);
  const [loadingDiagnostics, setLoadingDiagnostics] = useState(false);
  const [catalogStatus, setCatalogStatus] = useState<EgxCatalogStatus | null>(null);
  const [refreshingCatalog, setRefreshingCatalog] = useState(false);
  const [appVersion, setAppVersion] = useState("");
  const [openSection, setOpenSection] = useState<string>("ai");

  const toggleSection = (key: string) => setOpenSection((cur) => cur === key ? "" : key);

  const provider = (values.ai_provider || status?.ai_provider || "qwen") as AiProvider;

  const providerDetails: Record<AiProvider, { label: string; placeholder?: string; key?: keyof SettingsInput }> = {
    qwen: { label: "Qwen Cloud", placeholder: "sk-...", key: "qwen_api_key" },
    openrouter: { label: "OpenRouter", placeholder: "sk-or-...", key: "openrouter_api_key" },
    huggingface: { label: "Hugging Face", placeholder: "hf_...", key: "huggingface_api_key" },
    openai: { label: "OpenAI", placeholder: "sk-...", key: "openai_api_key" },
    ollama: { label: "Ollama Local" },
  };
  const currentProvider = providerDetails[provider];
  const localProvider = provider === "ollama";
  const selectedModel = localProvider
    ? values.ollama_model || status?.ollama_model || "qwen3-vl:4b"
    : values.openai_model || "";

  useEffect(() => { void getVersion().then(setAppVersion).catch(() => setAppVersion("Unknown")); }, []);
  useEffect(() => { void api.egxCatalog().then(setCatalogStatus).catch(() => setCatalogStatus(null)); }, [api]);
  useEffect(() => {
    if (status) setValues((cur) => ({
      ...cur,
      ai_provider: status.ai_provider,
      openai_model: status.openai_model,
      ollama_model: status.ollama_model,
      ollama_base_url: status.ollama_base_url,
      analysis_instructions: status.analysis_instructions,
    }));
  }, [status]);

  const save = (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    void api.saveSettings(values)
      .then(onSaved)
      .then(() => {
        setValues((cur) => ({
          ai_provider: cur.ai_provider, openai_model: cur.openai_model, ollama_model: cur.ollama_model,
          ollama_base_url: cur.ollama_base_url, analysis_instructions: cur.analysis_instructions,
        }));
        setEditingProviderKey(false);
        setEditingTelegram(false);
        notify("success", "Settings saved securely on this computer.");
      })
      .catch((reason) => showError(`Could not save settings: ${fullError(reason)}`))
      .finally(() => setSaving(false));
  };

  const chooseProvider = (next: AiProvider) => {
    const defaultModel = next === "qwen" ? "qwen3-vl-plus" : next === "openrouter" ? "openrouter/free" : "";
    setValues((cur) => next === "ollama"
      ? { ...cur, ai_provider: next, ollama_model: cur.ollama_model || "qwen3-vl:4b" }
      : { ...cur, ai_provider: next, openai_model: defaultModel });
    setEditingProviderKey(false);
  };

  const replaceKey = () => {
    if (!currentProvider.key) return;
    if (editingProviderKey) setValues((cur) => ({ ...cur, [currentProvider.key as keyof SettingsInput]: undefined }));
    setEditingProviderKey((cur) => !cur);
  };

  return (
    <div className="settings">

      <div className="settings-overview" aria-label="Current configuration">
        <span><strong>AI</strong> {providerDetails[provider].label} · {selectedModel || "No model selected"}</span>
        <span><strong>Telegram</strong> {status?.telegram_authorized ? "Connected" : "Not connected"}</span>
        <span><strong>Catalog</strong> {catalogStatus ? `${catalogStatus.stock_count} stocks` : "Loading"}</span>
        <span><strong>App</strong> v{appVersion || "..."}</span>
      </div>

      <SettingsSection title="AI Analysis" description={`${providerDetails[provider].label} · ${status?.ai_configured ? "configured" : "not configured"}`} open={openSection === "ai"} onToggle={() => toggleSection("ai")}>
        <form onSubmit={save}>
          <p>{localProvider ? "Ollama runs the selected model on this computer. Install the model manually, then load the installed vision models below." : "Cloud provider keys are encrypted and stored only on this computer."}</p>
          <label>
            AI provider
            <select value={provider} onChange={(e) => chooseProvider(e.target.value as AiProvider)}>
              <option value="ollama">Ollama Local - use a downloaded model</option>
              <option value="qwen">Qwen Cloud — default for Arabic and charts</option>
              <option value="openrouter">OpenRouter — free models available</option>
              <option value="huggingface">Hugging Face Inference Providers</option>
              <option value="openai">OpenAI</option>
            </select>
          </label>
          {!localProvider && <div className="credential-header">
            <div>
              <strong>{currentProvider.label}</strong>
              <span>{status?.ai_provider === provider && status.ai_configured ? "API key saved" : "API key not configured"}</span>
            </div>
            <button type="button" className="secondary" onClick={replaceKey}>
              {editingProviderKey ? "Cancel" : status?.ai_provider === provider && status.ai_configured ? "Replace API key" : "Add API key"}
            </button>
          </div>}
          {editingProviderKey && !localProvider && (
            <label>
              {`New ${currentProvider.label} API key`}
              <input type="password" autoComplete="new-password" placeholder={currentProvider.placeholder}
                value={(values[currentProvider.key!] as string) || ""}
                onChange={(e) => setValues((cur) => ({ ...cur, [currentProvider.key!]: e.target.value }))} required />
            </label>
          )}
          {localProvider && (
            <label>
              Ollama local service URL
              <input type="url" value={values.ollama_base_url || "http://127.0.0.1:11434"}
                onChange={(e) => setValues((cur) => ({ ...cur, ollama_base_url: e.target.value }))} required />
              <span className="credential-note">Default: http://127.0.0.1:11434. Telegram data remains on this computer while using Ollama.</span>
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
            configured={Boolean(status?.ai_provider === provider && (localProvider || status.ai_configured))}
            selected={selectedModel}
            onChange={(model) => setValues((cur) => localProvider ? { ...cur, ollama_model: model } : { ...cur, openai_model: model })}
            showError={showError}
          />
          <label>
            Supplementary extraction guidance
            <textarea
              value={values.analysis_instructions || ""}
              onChange={(e) => setValues((cur) => ({ ...cur, analysis_instructions: e.target.value }))}
              placeholder="For example: prioritize EGX table rows, preserve entries and targets exactly as posted, and flag conflicting channel details."
              rows={6}
            />
            <span className="credential-note">
              Optional source-specific guidance sent with each analysis. Fixed EGX eligibility, inquiry separation, and JSON output rules remain enforced.
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

        {status?.telegram_authorized && (
          <div className="settings-subsection">
            <strong>Fetch active channels now</strong>
            <p>Fetches recent messages only. It does not run AI analysis; use Channels when you are ready to analyze selected chats.</p>
            <button type="button" disabled={checkingTelegram} onClick={() => {
              setCheckingTelegram(true);
              void api.runCollection()
                .then(onRunTelegramCheck)
                .then(() => notify("success", "Telegram check completed."))
                .catch((reason) => showError(`Telegram check failed: ${fullError(reason)}`))
                .finally(() => setCheckingTelegram(false));
            }}>
              {checkingTelegram ? "Checking Telegram…" : "Check Telegram now"}
            </button>
          </div>
        )}
      </SettingsSection>

      <SettingsSection title="EGX Stock Catalog" description={catalogStatus ? `${catalogStatus.stock_count} stocks · refreshes every ${catalogStatus.refresh_days} days` : "Loading local stock mappings"} open={openSection === "catalog"} onToggle={() => toggleSection("catalog")}>
        <div className="settings-subsection">
          <strong>Arabic and English stock identities</strong>
          <p>Downloads the EGX catalog only when due, then keeps codes, Arabic names, English names, and learned aliases on this computer for all analyses.</p>
          <p className="credential-note">
            {catalogStatus?.last_successful_refresh ? `Last updated: ${formatGeneratedAt(catalogStatus.last_successful_refresh)}` : "Using the built-in catalog until the first online refresh."}
          </p>
          <button type="button" disabled={refreshingCatalog} onClick={() => {
            setRefreshingCatalog(true);
            void api.refreshEgxCatalog()
              .then((result) => {
                setCatalogStatus(result);
                notify("success", `EGX catalog refreshed: ${result.stock_count} stocks are stored locally.`);
              })
              .catch((reason) => showError(`Could not refresh the EGX catalog: ${fullError(reason)}`))
              .finally(() => setRefreshingCatalog(false));
          }}>
            {refreshingCatalog ? "Refreshing catalog…" : "Refresh EGX catalog now"}
          </button>
        </div>
      </SettingsSection>

      <SettingsSection title="Appearance" description={`${themeMode === "light" ? "Light" : "Dark"} violet palette`} open={openSection === "appearance"} onToggle={() => toggleSection("appearance")}>
        <div className="settings-subsection appearance-settings">
          <strong>Application theme</strong>
          <p>Choose the lavender and violet theme that is most comfortable for your workspace. Your choice is saved on this computer.</p>
          <div className="theme-picker" role="radiogroup" aria-label="Application theme">
            <button type="button" className={`theme-option theme-option-light ${themeMode === "light" ? "is-selected" : ""}`} role="radio" aria-checked={themeMode === "light"} onClick={() => onThemeModeChange("light")}>
              <span className="theme-swatch" /><span><strong>Light</strong><small>Bright lavender workspace</small></span>
            </button>
            <button type="button" className={`theme-option theme-option-dark ${themeMode === "dark" ? "is-selected" : ""}`} role="radio" aria-checked={themeMode === "dark"} onClick={() => onThemeModeChange("dark")}>
              <span className="theme-swatch" /><span><strong>Dark</strong><small>Deep-indigo workspace</small></span>
            </button>
          </div>
        </div>
      </SettingsSection>

      <SettingsSection title="Application" description={`Version ${appVersion || "Loading"}`} open={openSection === "updates"} onToggle={() => toggleSection("updates")}>
        <div className="settings-subsection">
          <strong>Application updates</strong>
          <p>Checks for a signed EGX Analyzer update and keeps your local data unchanged.</p>
          <button type="button" disabled={checkingUpdate} onClick={onCheckForUpdates}>
            {checkingUpdate ? "Checking…" : "Check for updates"}
          </button>
        </div>
      </SettingsSection>

      <SettingsSection title="Support and diagnostics" description="Local request logs and error traces" open={openSection === "diagnostics"} onToggle={() => toggleSection("diagnostics")}>
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
        <p>{update.body || "A newer, signed version of EGX Analyzer is ready."}</p>
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
