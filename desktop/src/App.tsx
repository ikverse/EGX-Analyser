import { FormEvent, Fragment, isValidElement, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type React from "react";
import { createPortal } from "react-dom";
import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { getVersion } from "@tauri-apps/api/app";
import { check } from "@tauri-apps/plugin-updater";

import {
  AiProvider, AnalysisContentType, AnalysisMode, AnalysisPerformance, AnalysisResultHistory, ApiClient, Channel, ClientInquiryResponse, EgxCatalogStatus, ModelRetryAudit,
  DiagnosticEntry, SettingsInput, SettingsStatus, TelegramChat,
  StockSourceRow, StockSourceTableRow, StockSummaryRow,
} from "./api";
import { cairoDateInputValue, formatCairoDateTime } from "./time";

type Page = "Channels" | "Results" | "Settings";
type ThemeMode = "light" | "dark";
type Toast = { kind: "success" | "warning"; text: string } | null;
type AnalysisRunState = { running: boolean; progress: string; startedAt?: number; requestId?: string; stopping?: boolean };
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
type IconName = "channels" | "results" | "settings" | "sidebar" | "refresh" | "copy" | "check" | "plus" | "download" | "users" | "clear" | "play" | "eye" | "trash" | "image" | "warning" | "info" | "history" | "chevron-right" | "chevron-down";

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
      case "sidebar": return <><rect {...common} x="3" y="4" width="18" height="16" rx="2" /><path {...common} d="M9 4v16" /><path {...common} d="m14 9 3 3-3 3" /></>;
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
      case "warning": return <><path {...common} d="M10.3 4.2 2.5 18a2 2 0 0 0 1.8 3h15.4a2 2 0 0 0 1.8-3L13.7 4.2a2 2 0 0 0-3.4 0Z" /><path {...common} d="M12 9v4M12 17h.01" /></>;
      case "info": return <><circle {...common} cx="12" cy="12" r="9" /><path {...common} d="M12 11v5M12 8h.01" /></>;
      case "history": return <><path {...common} d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path {...common} d="M3 3v5h5M12 7v5l3 2" /></>;
      case "chevron-right": return <path {...common} d="m9 18 6-6-6-6" />;
      case "chevron-down": return <path {...common} d="m6 9 6 6 6-6" />;
    }
  })();
  return <svg className="icon" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">{paths}</svg>;
}

function normalizeChannelHandle(value: string): string {
  return value.trim().replace(/^@/, "").toLocaleLowerCase();
}

function formatElapsedTime(startedAt?: number): string {
  if (!startedAt) return "";
  const totalSeconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  if (totalSeconds < 60) return `${totalSeconds}s`;
  return `${Math.floor(totalSeconds / 60)}m ${totalSeconds % 60}s`;
}

function AnalysisRunningStatus({ progress, startedAt }: { progress: string; startedAt?: number }) {
  const [, setTick] = useState(0);

  useEffect(() => {
    const interval = window.setInterval(() => setTick((current) => current + 1), 1_000);
    return () => window.clearInterval(interval);
  }, []);

  return (
    <span className="analysis-running-chip" title={progress}>
      <span className="online-dot" />
      <strong>Analysis running</strong>
      <small>{progress} · {formatElapsedTime(startedAt)}</small>
    </span>
  );
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

function loadSidebarExpanded(): boolean {
  return localStorage.getItem("egx.sidebarExpanded") === "true";
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
  const [sidebarExpanded, setSidebarExpanded] = useState(loadSidebarExpanded);
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
  const [successModal, setSuccessModal] = useState<{ message: string; resultId?: number } | null>(null);
  const [focusedResultId, setFocusedResultId] = useState<number | null>(null);
  const [availableUpdate, setAvailableUpdate] = useState<UpdateCandidate | null>(null);
  const [checkingUpdate, setCheckingUpdate] = useState(false);
  const [downloadingUpdate, setDownloadingUpdate] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState<number | null>(null);
  const api = useMemo(() => new ApiClient(), []);
  const analysisAbortRef = useRef<AbortController | null>(null);
  const analysisStopRequestedRef = useRef(false);

  useEffect(() => {
    document.documentElement.dataset.theme = themeMode;
    localStorage.setItem("egx.theme", themeMode);
  }, [themeMode]);

  useEffect(() => {
    localStorage.setItem("egx.sidebarExpanded", String(sidebarExpanded));
  }, [sidebarExpanded]);

  const notify = (kind: "success" | "warning", text: string) => setToast({ kind, text });

  const showError = useCallback((fullText: string) => {
    setErrorModal(fullText);
    const short = fullText.length > 120 ? `${fullText.slice(0, 117)}…` : fullText;
    setToast({ kind: "warning", text: short });
  }, []);
  const showSuccess = useCallback((message: string, resultId?: number) => setSuccessModal({ message, resultId }), []);

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
    const requestId = crypto.randomUUID();
    const abortController = new AbortController();
    analysisAbortRef.current = abortController;
    analysisStopRequestedRef.current = false;
    setAnalysisRun({ running: true, progress: "Collecting selected chat data...", startedAt: Date.now(), requestId });
    const progressTimers = [
      window.setTimeout(() => setAnalysisRun((current) => current.stopping ? current : ({ ...current, progress: "Preparing selected text, images, and audio..." })), 1_500),
      window.setTimeout(() => setAnalysisRun((current) => current.stopping ? current : ({ ...current, progress: "Analyzing selected content with the AI model..." })), 5_000),
      window.setTimeout(() => setAnalysisRun((current) => current.stopping ? current : ({ ...current, progress: "Saving the analysis result..." })), 20_000),
    ];
    void api.analyzeSelected(
      channelIds,
      analysisConfig.contentTypes,
      analysisConfig.mode,
      analysisConfig.mode === "specific_date" ? analysisConfig.targetDate : undefined,
      requestId,
      abortController.signal,
    )
      .then(async (result) => {
        await refresh(false);
        setAnalysisResults(await api.analysisResults());
        if (analysisStopRequestedRef.current) {
          notify("warning", "The analysis finished before it could be stopped, so its result was saved.");
          return;
        }
        const noStockContext = result.not_stock_related.length
          ? ` No stock-related context: ${result.not_stock_related.join(", ")}.`
          : "";
        showSuccess(
          `${result.messages_analyzed} of ${result.messages_in_window} messages were analyzed. ` +
          `Target suggestion date: ${result.target_date}. Inputs sent: ${contentTypeLabel(result.content_types)}. ` +
          `The result is now available in Results.${noStockContext}`,
          result.report.id,
        );
      })
      .catch((reason) => {
        if (analysisStopRequestedRef.current || (reason instanceof Error && reason.name === "AbortError")) {
          notify("warning", "Analysis stopped. No incomplete result was saved.");
          return;
        }
        showError(fullError(reason));
      })
      .finally(() => {
        progressTimers.forEach((timer) => window.clearTimeout(timer));
        analysisAbortRef.current = null;
        analysisStopRequestedRef.current = false;
        setAnalysisRun({ running: false, progress: "" });
      });
  }, [analysisConfig, analysisRun.running, api, notify, refresh, showError, showSuccess]);

  const stopAnalysis = useCallback(() => {
    if (!analysisRun.running || !analysisRun.requestId || analysisRun.stopping) return;
    analysisStopRequestedRef.current = true;
    setAnalysisRun((current) => ({ ...current, stopping: true, progress: "Stopping the analysis request..." }));
    void api.cancelAnalysis(analysisRun.requestId)
      .then(({ cancelled }) => {
        analysisAbortRef.current?.abort();
        if (!cancelled) notify("warning", "The analysis was already finishing when the stop request arrived.");
      })
      .catch((reason) => {
        analysisStopRequestedRef.current = false;
        setAnalysisRun((current) => ({ ...current, stopping: false, progress: "Analysis is still running. Stop could not be confirmed." }));
        showError(`Could not stop the analysis: ${fullError(reason)}`);
      });
  }, [analysisRun.requestId, analysisRun.running, analysisRun.stopping, api, notify, showError]);

  const installUpdate = async () => {
    if (!availableUpdate) return;
    setDownloadingUpdate(true);
    setDownloadProgress(0);
    let downloaded = 0;
    let contentLength = 0;
    let engineStoppedForInstall = false;
    try {
      await invoke("prepare_for_update");
      engineStoppedForInstall = true;
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
      if (engineStoppedForInstall) {
        try {
          await invoke("restore_local_engine");
        } catch (restoreReason) {
          console.error("Could not restore the local engine after a failed update", restoreReason);
        }
      }
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
      <main className="startup-screen">
        <div className="startup-card">
          <div className="startup-brand">
            <div className="startup-logo"><img src="/branding/egx-analyzer-icon.png" alt="" /></div>
            <div>
              <span>EGX market intelligence</span>
              <h1>EGX Analyzer</h1>
            </div>
          </div>
          <div className="startup-intro">
            <h2>{engineStarting ? "Preparing your workspace" : "Restarting your workspace"}</h2>
            <p>Loading your channels, analysis history, and locally stored settings.</p>
          </div>
          <div className="startup-status" role="status" aria-live="polite">
            <span className="startup-spinner" aria-hidden="true" />
            <div>
              <strong>Local engine</strong>
              <span>{engineStarting ? "Starting services…" : "Reconnecting services…"}</span>
            </div>
          </div>
          <div className="startup-progress" aria-hidden="true"><span /></div>
          <div className="startup-details">
            <span>Cairo market workflow</span>
            <span>Local results storage</span>
          </div>
        </div>
      </main>
    );
  }

  return (
    <>
      <main className={`shell ${sidebarExpanded ? "sidebar-expanded" : "sidebar-collapsed"}`}>
        <aside className="app-sidebar">
          <div className="sidebar-header">
            <h1 className="brand-title" title="EGX Analyzer"><img src="/branding/egx-analyzer-icon.png" alt="" /><span>EGX Analyzer</span></h1>
            <button
              type="button"
              className="sidebar-toggle"
              onClick={() => setSidebarExpanded((current) => !current)}
              aria-label={sidebarExpanded ? "Collapse navigation" : "Expand navigation"}
              aria-expanded={sidebarExpanded}
              title={sidebarExpanded ? "Collapse navigation" : "Expand navigation"}
            >
              <Icon name="sidebar" />
            </button>
          </div>
          <nav className="sidebar-nav" aria-label="Primary navigation">
            {pages.map((item) => (
              <button
                className={`sidebar-nav-button ${page === item ? "active" : ""}`}
                onClick={() => setPage(item)}
                key={item}
                title={sidebarExpanded ? undefined : item}
                aria-label={item}
              >
                <Icon name={PAGE_ICONS[item]} /><span className="sidebar-label">{item}</span>
              </button>
            ))}
          </nav>
          <div className="sidebar-theme-control">
            <div>
              <strong>Appearance</strong>
              <span>{themeMode === "dark" ? "Dark mode" : "Light mode"}</span>
            </div>
            <button
              type="button"
              className="sidebar-theme-switch"
              role="switch"
              aria-checked={themeMode === "light"}
              aria-label={`Switch to ${themeMode === "dark" ? "light" : "dark"} mode`}
              title={`Switch to ${themeMode === "dark" ? "light" : "dark"} mode`}
              onClick={() => setThemeMode((current) => current === "dark" ? "light" : "dark")}
            >
              <span />
            </button>
          </div>
        </aside>
        <section>
          <header>
            <div>
              <strong>{page}</strong>
            </div>
            <div className="header-actions">
              {analysisRun.running && <AnalysisRunningStatus progress={analysisRun.progress} startedAt={analysisRun.startedAt} />}
              {analysisRun.running && <button className="danger compact" onClick={stopAnalysis} disabled={analysisRun.stopping}>
                <Icon name="clear" /> {analysisRun.stopping ? "Stopping..." : "Stop analysis"}
              </button>}
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
              settings={settings}
              api={api}
              refresh={refresh}
              notify={notify}
              showError={showError}
              analysisRun={analysisRun}
              analysisConfig={analysisConfig}
              updateAnalysisConfig={updateAnalysisConfig}
              onAnalyze={runAnalysis}
              onStopAnalysis={stopAnalysis}
              onModelChange={async (model) => {
                if (!settings) throw new Error("Settings are still loading.");
                const saved = await api.saveSettings(settings.ai_provider === "ollama"
                  ? { ollama_model: model }
                  : { openai_model: model });
                setSettings(saved);
                notify("success", `Analysis model set to ${model}.`);
              }}
            />
          )}
          {page === "Results" && (
            <Results
              api={api}
              notify={notify}
              showError={showError}
              analysisResults={analysisResults}
              onAnalysisDeleted={(id) => setAnalysisResults((current) => current.filter((item) => item.id !== id))}
              focusedResultId={focusedResultId}
              onFocusHandled={() => setFocusedResultId(null)}
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
              analysisResults={analysisResults}
            />
          )}
        </section>
      </main>

      {errorModal && <ErrorModal message={errorModal} onClose={() => setErrorModal(null)} />}
      {successModal && <SuccessModal
        message={successModal.message}
        onClose={() => setSuccessModal(null)}
        onOpenResult={successModal.resultId ? () => {
          setPage("Results");
          setFocusedResultId(successModal.resultId!);
          setSuccessModal(null);
        } : undefined}
      />}

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

function Channels({ channels, settings, api, refresh, notify, showError, analysisRun, analysisConfig, updateAnalysisConfig, onAnalyze, onStopAnalysis, onModelChange }: {
  channels: Channel[]; settings: SettingsStatus | null; api: ApiClient;
  refresh: () => Promise<boolean>; notify: Notify; showError: ShowError;
  analysisRun: AnalysisRunState; analysisConfig: ChannelAnalysisConfig;
  updateAnalysisConfig: (updater: (current: ChannelAnalysisConfig) => ChannelAnalysisConfig) => void;
  onAnalyze: (channelIds: number[]) => void;
  onStopAnalysis: () => void;
  onModelChange: (model: string) => Promise<void>;
}) {
  const [chatQuery, setChatQuery] = useState("");
  const [chats, setChats] = useState<TelegramChat[]>(() => {
    try { return JSON.parse(sessionStorage.getItem("egx.telegramChats") || "[]") as TelegramChat[]; }
    catch { return []; }
  });
  const [loading, setLoading] = useState(false);
  const [refreshingChats, setRefreshingChats] = useState(false);
  const latestHistoricalDate = useMemo(cairoDateInputValue, []);
  const { selectedHandles, contentTypes, mode: analysisMode, targetDate } = analysisConfig;
  const busy = loading || analysisRun.running;
  const analyzing = analysisRun.running;
  const analysisProgress = analysisRun.progress;

  const loadChats = () => {
    setLoading(true);
    setRefreshingChats(true);
    void api.telegramChats()
      .then((items) => {
        setChats(items);
        sessionStorage.setItem("egx.telegramChats", JSON.stringify(items));
        notify(items.length ? "success" : "warning",
          items.length ? `${items.length} Telegram chats loaded for this session.` : "No chats were found.");
      })
      .catch((reason) => showError(fullError(reason)))
      .finally(() => {
        setLoading(false);
        setRefreshingChats(false);
      });
  };

  useEffect(() => {
    if (!settings?.telegram_authorized || sessionStorage.getItem("egx.telegramChatsLoadedAtStartup") === "true") return;
    sessionStorage.setItem("egx.telegramChatsLoadedAtStartup", "true");
    loadChats();
  }, [settings?.telegram_authorized]);

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
        <p className="section-description">Telegram chats load automatically when the app starts. Refresh them here whenever your chat list changes.</p>
        <button className="secondary load-chats-button" onClick={loadChats} disabled={busy}>
          <Icon name="refresh" /> {refreshingChats ? "Refreshing Telegram chats…" : "Refresh Telegram chats"}
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
                    <td>
                      <label className="channel-selection-control" onClick={(event) => event.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          disabled={busy}
                          aria-label={`${isSelected ? "Remove" : "Select"} ${chat.title}`}
                          onChange={() => toggleChatSelection(chat)}
                        />
                        <span className={isSelected ? "channel-selection-state selected" : "channel-selection-state"}>{isSelected ? "Selected" : "Select"}</span>
                      </label>
                    </td>
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
        <div className="analysis-action-bar">
          <div className="analysis-action-controls">
            <ModelSelector
              api={api}
              configured={Boolean(settings?.ai_configured || settings?.ai_provider === "ollama")}
              selected={settings?.ai_provider === "ollama" ? settings.ollama_model : settings?.openai_model || ""}
              onChange={onModelChange}
              showError={showError}
              compact
            />
            <button
              className={`analysis-submit-button${analyzing ? " danger" : ""}`}
              onClick={analyzing ? onStopAnalysis : analyze}
              disabled={loading || analysisRun.stopping}
            >
              <Icon name={analyzing ? "clear" : "play"} />
              <span>{analysisRun.stopping ? "Stopping analysis..." : analyzing ? "Stop analysis" : "Analyze selected chats"}</span>
            </button>
          </div>
          {analyzing && <p className="analysis-progress" role="status" aria-live="polite">{analysisProgress}</p>}
        </div>
      </div>
    </>
  );
}

// ── Results (merged Recommendations + Search) ─────────────────────────────────

function Results({ api, notify, showError, analysisResults, onAnalysisDeleted, focusedResultId, onFocusHandled }: {
  api: ApiClient;
  notify: Notify; showError: ShowError; analysisResults: AnalysisResultHistory[];
  onAnalysisDeleted: (id: number) => void;
  focusedResultId: number | null;
  onFocusHandled: () => void;
}) {
  return (
    <AnalysisResultHistoryTable
      items={analysisResults}
      api={api}
      notify={notify}
      showError={showError}
      onDeleted={onAnalysisDeleted}
      focusedResultId={focusedResultId}
      onFocusHandled={onFocusHandled}
    />
  );
}

function formatGeneratedAt(value: string): string {
  return formatCairoDateTime(value);
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

function AnalysisRunOverview({ item }: { item: AnalysisResultHistory }) {
  const stockCount = new Set(item.stock_source_table.map((row) => row.ticker)).size;
  const sourceCount = new Set([
    ...item.stock_source_table.map((row) => row.source),
    ...item.client_inquiry_responses.map((row) => row.source),
  ].filter(Boolean)).size;

  return <section className="analysis-run-overview" aria-label="Analysis run overview">
    <span>{contentTypeLabel(item.content_types)} analyzed</span>
    <span>{sourceCount} source{sourceCount === 1 ? "" : "s"}</span>
    <span>{stockCount} stock{stockCount === 1 ? "" : "s"}</span>
    <span>{item.stock_source_table.length} recommendation{item.stock_source_table.length === 1 ? "" : "s"}</span>
    <span>{item.client_inquiry_responses.length} inquiry {item.client_inquiry_responses.length === 1 ? "reply" : "replies"}</span>
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

function AnalysisResultHistoryTable({ items, api, notify, showError, onDeleted, focusedResultId, onFocusHandled }: {
  items: AnalysisResultHistory[]; api: ApiClient; notify: Notify; showError: ShowError; onDeleted: (id: number) => void;
  focusedResultId: number | null;
  onFocusHandled: () => void;
}) {
  const [expandedAnalysis, setExpandedAnalysis] = useState<number | null>(null);
  const [expandedSection, setExpandedSection] = useState<"recommendations" | "inquiries" | null>(null);
  const [stockQuery, setStockQuery] = useState("");
  const [deleteCandidate, setDeleteCandidate] = useState<AnalysisResultHistory | null>(null);
  const [deleting, setDeleting] = useState(false);
  const rowRefs = useRef(new Map<number, HTMLTableRowElement>());

  useEffect(() => {
    if (focusedResultId === null || !items.some((item) => item.id === focusedResultId)) return;
    setExpandedAnalysis(focusedResultId);
    setExpandedSection("recommendations");
    const frame = window.requestAnimationFrame(() => {
      rowRefs.current.get(focusedResultId)?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
    const timer = window.setTimeout(onFocusHandled, 2_500);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [focusedResultId, items, onFocusHandled]);
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

  return (
    <div className="analysis-history-wrap">
      <table className="analysis-history-table">
        <colgroup>
          <col className="analysis-history-output-col" />
          <col className="analysis-history-generated-col" />
          <col className="analysis-history-sources-col" />
          <col className="analysis-history-findings-col" />
          <col className="analysis-history-actions-col" />
        </colgroup>
        <thead>
          <tr><th>Generated output</th><th>Generated at</th><th>Sources</th><th>Findings</th><th className="analysis-history-actions-heading">Actions</th></tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const analysisOpen = expandedAnalysis === item.id;
            const recommendationsOpen = analysisOpen && expandedSection === "recommendations";
            const inquiriesOpen = analysisOpen && expandedSection === "inquiries";
            const stockCount = new Set(item.stock_source_table.map((row) => row.ticker)).size;
            const sources = [...new Set([
              ...item.stock_source_table.map((row) => row.source),
              ...item.client_inquiry_responses.map((row) => row.source),
            ].filter(Boolean))];
            return (
              <Fragment key={item.id}>
                <tr
                  className={`analysis-history-row ${focusedResultId === item.id ? "is-focused" : ""}`}
                  onClick={() => toggleAnalysis(item.id)}
                  ref={(element) => {
                    if (element) rowRefs.current.set(item.id, element);
                    else rowRefs.current.delete(item.id);
                  }}
                >
                  <td><strong>Analysis Recommendations · {item.target_date || "No target date"}</strong></td>
                  <td>{formatGeneratedAt(item.generated_at)}</td>
                  <td>{sources.join(", ") || "—"}</td>
                  <td className="analysis-history-findings">
                    <strong>{stockCount} stock{stockCount === 1 ? "" : "s"}</strong>
                    <span>{item.stock_source_table.length} recommendation{item.stock_source_table.length === 1 ? "" : "s"}</span>
                    <span>{item.client_inquiry_responses.length} inquiry {item.client_inquiry_responses.length === 1 ? "reply" : "replies"}</span>
                  </td>
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
                    <td colSpan={5}>
                      <AnalysisRunOverview item={item} />
                      <div className="analysis-section-list">
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

function entryDisplay(value: unknown, low?: unknown, high?: unknown): string {
  const hasLow = low !== undefined && low !== null && low !== "";
  const hasHigh = high !== undefined && high !== null && high !== "";
  if (hasLow && hasHigh) return `${num(low)}–${num(high)}`;
  return num(value);
}

function dateBasisLabel(basis: string): string {
  const normalized = basis.trim().toLowerCase().replace(/[\s-]+/g, "_");
  const labels: Record<string, string> = {
    explicit_date: "Explicit date",
    t_plus_1: "T+1",
    watching: "Watching",
    watch: "Watching",
    watchlist: "Watching",
    watch_list: "Watching",
    under_watch: "Watching",
    stock_to_watch: "Watching",
    next_session: "Next session",
    tomorrow: "Tomorrow",
  };
  return labels[normalized] ?? basis;
}

function SuccessModal({ message, onClose, onOpenResult }: { message: string; onClose: () => void; onOpenResult?: () => void }) {
  return (
    <div className="error-modal-backdrop" role="dialog" aria-modal="true" aria-label="Analysis completed">
      <div className="error-modal-card success-modal-card">
        <h2 className="error-modal-title success-modal-title">Analysis completed</h2>
        <p className="success-modal-body">{message}</p>
        <div className="error-modal-actions">
          {onOpenResult && <button type="button" className="secondary" onClick={onOpenResult}><Icon name="eye" /> Open result</button>}
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
        <div>
          <strong>EGX recommendations by source</strong>
          <span>Each row preserves one model-returned dated recommendation without combining source values.</span>
        </div>
        <div className="consolidated-table-tools">
          <span className="table-scroll-hint">Scroll horizontally to view every price field</span>
        </div>
      </div>
      <div className="consolidated-table-scroll">
        <table className="consolidated-table">
          <thead><tr>
            <th>Source</th><th>Target date</th><th>Source date</th><th>Timing</th><th>Type</th><th>Entry</th><th>TP1</th><th>TP2</th>
            <th>Stop</th><th>Support</th><th>Resistance</th><th>Return %</th><th>Risk %</th><th>Status</th><th>Source image</th><th>Notes</th>
          </tr></thead>
          {[...grouped.entries()].map(([ticker, stockRows]) => {
            const first = stockRows[0];
            return (
              <tbody key={ticker}>
                <tr className="consolidated-stock-group"><td colSpan={16}>
                  <div className="consolidated-stock-group-content">
                    <span className="consolidated-rank">#{first.rank ?? "—"}</span>
                    <strong>{first.ticker}</strong>
                    <span>{first.company}</span>
                    {first.company_ar && <span className="consolidated-company-ar">{first.company_ar}</span>}
                    <span className="consolidated-mentions">{first.mention_count} total mentions</span>
                  </div>
                </td></tr>
                {stockRows.map((row, rowIndex) => (
                  <tr key={`${row.ticker}-${row.source}-${row.latest_date ?? "unknown"}-${row.buy_price ?? "none"}`}>
                    <td className="source-cell">{row.source}</td>
                    <td className="target-date-cell">{row.target_date || "—"}</td>
                    <td>{row.source_dates.join(", ") || "—"}</td>
                    <td>{row.effective_date_bases?.length ? row.effective_date_bases.map((basis) => <span key={basis} className="recommendation-date-basis">{dateBasisLabel(basis)}</span>) : "—"}</td>
                    <td><span className={`status-pill ${row.recommendation_type === "sell" ? "neutral" : "active"}`}>{row.recommendation_type || "buy"}</span></td>
                    <td className="numeric">{entryDisplay(row.buy_price, row.buy_price_low, row.buy_price_high)}</td>
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
                    {rowIndex === 0 && <td className="analysis-summary" rowSpan={stockRows.length}>{first.notes_summary || "—"}</td>}
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
            <div className="client-inquiry-group-heading">
              <h4>
                <span className="client-inquiry-ticker" dir="ltr">{ticker}</span>
                {first.company_ar && <span>{first.company_ar}</span>}
                {first.company && <span className="client-inquiry-company-en" dir="ltr">{first.company}</span>}
              </h4>
              <span>{replies.length === 1 ? "رد واحد" : `${replies.length} ردود`}</span>
            </div>
            <div className={`client-inquiry-cards${replies.length === 1 ? " is-single" : ""}`}>
              {replies.map((row, index) => <ClientInquiryCard key={`${row.source}-${row.date ?? ""}-${row.source_message_id ?? index}`} row={row} />)}
            </div>
          </section>
        );
      })}
    </section>
  );
}

function ClientInquiryCard({ row }: { row: ClientInquiryResponse }) {
  const availableLevels = (levels: Array<[string, string | number | null | undefined]>) => levels
    .filter(([, value]) => value !== undefined && value !== null)
    .map(([label, value]) => [label, num(value)] as const);
  const hasEntry = [row.buy_price, row.buy_price_low, row.buy_price_high]
    .some((value) => value !== undefined && value !== null);
  const entry = hasEntry ? entryDisplay(row.buy_price, row.buy_price_low, row.buy_price_high) : null;
  const tradeLevels = availableLevels([
    ["سعر الدخول", entry], ["الهدف الأول", row.target_1], ["الهدف الثاني", row.target_2], ["وقف الخسارة", row.stop_loss],
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

function ModelSelector({ api, configured, selected, onChange, showError, compact = false }: {
  api: ApiClient; configured: boolean; selected: string;
  onChange: (value: string) => Promise<void>; showError: ShowError; compact?: boolean;
}) {
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

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

  const choose = (value: string) => {
    setSaving(true);
    void onChange(value)
      .catch((reason) => showError(`Could not change the analysis model: ${fullError(reason)}`))
      .finally(() => setSaving(false));
  };

  return (
    <label className={compact ? "model-selector model-selector-compact" : "model-selector"}>
      Analysis model
      {!compact && <small className="model-selector-help">Shows every model currently available from the selected provider. Choose a vision-capable model when analyzing photos.</small>}
      <div className="model-row">
        <select value={selected} onChange={(e) => choose(e.target.value)} disabled={!configured || saving}>
          <option value={selected}>{selected || "Choose a model"}</option>
          {models.filter((m) => m !== selected).map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <button type="button" onClick={() => void load(true)} disabled={!configured || loading || saving}>
          {loading ? "Loading…" : "Load models"}
        </button>
      </div>
    </label>
  );
}

// ── CloudSettings ─────────────────────────────────────────────────────────────

function SettingsInfo({ id, title, text, openInfoId, setOpenInfoId }: {
  id: string; title: string; text: string; openInfoId: string | null;
  setOpenInfoId: React.Dispatch<React.SetStateAction<string | null>>;
}) {
  const buttonRef = useRef<HTMLButtonElement>(null);
  const popupRef = useRef<HTMLSpanElement>(null);
  const open = openInfoId === id;
  const [position, setPosition] = useState({ left: 12, top: 12 });

  const placePopup = useCallback(() => {
    const button = buttonRef.current;
    if (!button) return;
    const rect = button.getBoundingClientRect();
    const width = Math.max(0, Math.min(336, window.innerWidth - 24));
    const height = popupRef.current?.offsetHeight ?? 220;
    const left = Math.min(window.innerWidth - width - 12, Math.max(12, rect.left + rect.width / 2 - width / 2));
    const below = rect.bottom + 8;
    const above = rect.top - height - 8;
    const preferredTop = below + height <= window.innerHeight - 12 ? below : above;
    const top = Math.min(window.innerHeight - height - 12, Math.max(12, preferredTop));
    setPosition({ left, top });
  }, []);

  useEffect(() => {
    if (!open) return;
    placePopup();
    const closeOutside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!buttonRef.current?.contains(target) && !popupRef.current?.contains(target)) setOpenInfoId(null);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpenInfoId(null);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    window.addEventListener("resize", placePopup);
    window.addEventListener("scroll", placePopup, true);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("resize", placePopup);
      window.removeEventListener("scroll", placePopup, true);
    };
  }, [open, placePopup, setOpenInfoId]);

  return (
    <span className="settings-info">
      <button
        ref={buttonRef}
        type="button"
        className="settings-info-button"
        aria-label={`Information about ${title}`}
        aria-expanded={open}
        aria-controls={`settings-info-${id}`}
        title={`About ${title}`}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setOpenInfoId((current) => current === id ? null : id);
        }}
      >
        <Icon name="info" size={15} />
      </button>
      {open && createPortal(
        <span
          ref={popupRef}
          id={`settings-info-${id}`}
          className="settings-info-popup"
          role="dialog"
          aria-label={title}
          style={{ left: position.left, top: position.top }}
        >
          <strong>{title}</strong>
          <span>{text}</span>
        </span>,
        document.body,
      )}
    </span>
  );
}

function SettingsLabel({ children, infoId, info, openInfoId, setOpenInfoId }: {
  children: React.ReactNode; infoId: string; info: string; openInfoId: string | null;
  setOpenInfoId: React.Dispatch<React.SetStateAction<string | null>>;
}) {
  return (
    <span className="settings-label-with-info">
      <span>{children}</span>
      <SettingsInfo id={infoId} title={typeof children === "string" ? children : "Setting information"} text={info}
        openInfoId={openInfoId} setOpenInfoId={setOpenInfoId} />
    </span>
  );
}

function SettingsSection({ id, title, description, help, open, onToggle, openInfoId, setOpenInfoId, children }: {
  id: string; title: string; description?: string; help: string; open: boolean; onToggle: () => void;
  openInfoId: string | null; setOpenInfoId: React.Dispatch<React.SetStateAction<string | null>>;
  children: React.ReactNode;
}) {
  const bodyId = `settings-section-${id}`;

  return (
    <div className={`settings-section${open ? " is-open" : ""}`}>
      <div className="settings-section-header">
        <button
          type="button"
          className="settings-section-toggle"
          aria-expanded={open}
          aria-controls={bodyId}
          aria-label={`${open ? "Collapse" : "Expand"} ${title}`}
          onClick={onToggle}
        />
        <div className="settings-section-copy">
          <div className="settings-section-title-row">
            <span className="settings-section-title">{title}</span>
            <SettingsInfo id={`section-${id}`} title={title} text={help}
              openInfoId={openInfoId} setOpenInfoId={setOpenInfoId} />
          </div>
          {description && <span className="settings-section-status">{description}</span>}
        </div>
        <span className="settings-section-chevron" aria-hidden="true">
          <Icon name={open ? "chevron-down" : "chevron-right"} size={17} />
        </span>
      </div>
      {open && <div id={bodyId} className="settings-section-body">{children}</div>}
    </div>
  );
}

function normalizePromptPhraseInput(value?: string): string[] {
  const seen = new Set<string>();
  return (value || "").split(/[,،]/).map((phrase) => phrase.trim().replace(/\s+/g, " ")).filter((phrase) => {
    const key = phrase.toLocaleLowerCase();
    if (!phrase || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function samePromptPhrases(first: string[], second: string[]): boolean {
  return first.length === second.length
    && first.every((phrase, index) => phrase.toLocaleLowerCase() === second[index]?.toLocaleLowerCase());
}

function CloudSettings({ api, status, onSaved, onRunTelegramCheck, notify, showError, checkingUpdate, onCheckForUpdates, analysisResults }: {
  api: ApiClient; status: SettingsStatus | null; onSaved: () => Promise<boolean>;
  onRunTelegramCheck: () => Promise<boolean>;
  notify: Notify; showError: ShowError; checkingUpdate: boolean; onCheckForUpdates: () => void;
  analysisResults: AnalysisResultHistory[];
}) {
  const [values, setValues] = useState<SettingsInput>({
    ai_provider: status?.ai_provider || "qwen",
    openai_model: status?.openai_model || "qwen3-vl-plus",
    ollama_model: status?.ollama_model || "qwen3-vl:4b",
    ollama_base_url: status?.ollama_base_url || "http://127.0.0.1:11434",
    analysis_include_phrases: status?.analysis_include_phrases || "",
    analysis_exclude_phrases: status?.analysis_exclude_phrases || "",
  });
  const [editingProviderKey, setEditingProviderKey] = useState(false);
  const [editingTelegram, setEditingTelegram] = useState(false);
  const [saving, setSaving] = useState(false);
  const [resettingPrompt, setResettingPrompt] = useState(false);
  const [restoringPromptIndex, setRestoringPromptIndex] = useState<number | null>(null);
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
  const [openInfoId, setOpenInfoId] = useState<string | null>(null);

  const toggleSection = (key: string) => {
    setOpenInfoId(null);
    setOpenSection((cur) => cur === key ? "" : key);
  };

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
  const configuredModel = status?.ai_provider === "ollama" ? status.ollama_model : status?.openai_model;
  const outputAudits = analysisResults.filter((item) => item.model_validation_warnings.length > 0);
  const includePhrases = normalizePromptPhraseInput(values.analysis_include_phrases);
  const excludePhrases = normalizePromptPhraseInput(values.analysis_exclude_phrases);
  const excludeKeys = new Set(excludePhrases.map((phrase) => phrase.toLocaleLowerCase()));
  const conflictingPhrases = includePhrases.filter((phrase) => excludeKeys.has(phrase.toLocaleLowerCase()));
  const effectiveIncludePhrases = includePhrases.filter((phrase) => !excludeKeys.has(phrase.toLocaleLowerCase()));
  const savedIncludePhrases = normalizePromptPhraseInput(status?.analysis_include_phrases);
  const savedExcludePhrases = normalizePromptPhraseInput(status?.analysis_exclude_phrases);
  const promptPhrasesDirty = !samePromptPhrases(effectiveIncludePhrases, savedIncludePhrases)
    || !samePromptPhrases(excludePhrases, savedExcludePhrases);
  const promptPreview = [
    "MANAGED RECOMMENDATION PHRASE GUIDANCE",
    `Include phrases: ${effectiveIncludePhrases.join(", ") || "(none)"}`,
    `Exclude phrases: ${excludePhrases.join(", ") || "(none)"}`,
    "Exclude phrases take priority. Existing stock identity, date eligibility, source, and output rules remain active.",
  ].join("\n");

  useEffect(() => { void getVersion().then(setAppVersion).catch(() => setAppVersion("Unknown")); }, []);
  useEffect(() => { void api.egxCatalog().then(setCatalogStatus).catch(() => setCatalogStatus(null)); }, [api]);
  useEffect(() => {
    if (status) setValues((cur) => ({
      ...cur,
      ai_provider: status.ai_provider,
      openai_model: status.openai_model,
      ollama_model: status.ollama_model,
      ollama_base_url: status.ollama_base_url,
      analysis_include_phrases: status.analysis_include_phrases,
      analysis_exclude_phrases: status.analysis_exclude_phrases,
    }));
  }, [status]);

  const save = (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    void api.saveSettings(values)
      .then((saved) => {
        setValues((cur) => ({
          ai_provider: cur.ai_provider, openai_model: cur.openai_model, ollama_model: cur.ollama_model,
          ollama_base_url: cur.ollama_base_url, analysis_include_phrases: saved.analysis_include_phrases,
          analysis_exclude_phrases: saved.analysis_exclude_phrases,
        }));
        return onSaved();
      })
      .then(() => {
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

  const resetPrompt = () => {
    if (!window.confirm("Reset the analysis prompt to its built-in defaults and remove all custom include/exclude phrases? The change log will be retained.")) return;
    setResettingPrompt(true);
    void api.resetPromptCustomization()
      .then((saved) => {
        setValues((cur) => ({
          ...cur,
          analysis_include_phrases: saved.analysis_include_phrases,
          analysis_exclude_phrases: saved.analysis_exclude_phrases,
        }));
        return onSaved();
      })
      .then(() => notify("success", "The default analysis prompt was restored."))
      .catch((reason) => showError(`Could not reset the analysis prompt: ${fullError(reason)}`))
      .finally(() => setResettingPrompt(false));
  };

  const restorePrompt = (historyIndex: number, timestamp: string) => {
    if (!window.confirm(`Restore the phrase configuration saved at ${formatCairoDateTime(timestamp)}? This restore will be added to the change log.`)) return;
    setRestoringPromptIndex(historyIndex);
    void api.restorePromptCustomization(historyIndex)
      .then((saved) => {
        setValues((cur) => ({
          ...cur,
          analysis_include_phrases: saved.analysis_include_phrases,
          analysis_exclude_phrases: saved.analysis_exclude_phrases,
        }));
        return onSaved();
      })
      .then(() => notify("success", "The selected phrase configuration was restored."))
      .catch((reason) => showError(`Could not restore the phrase configuration: ${fullError(reason)}`))
      .finally(() => setRestoringPromptIndex(null));
  };

  return (
    <div className="settings">

      <div className="settings-overview" aria-label="Current configuration">
        <span><strong>AI</strong><span className="settings-overview-value" title={`${providerDetails[provider].label} · ${configuredModel || "No model selected"}`}>{providerDetails[provider].label} · {configuredModel || "No model selected"}</span></span>
        <span><strong>Telegram</strong><span className="settings-overview-value">{status?.telegram_authorized ? "Connected" : "Not connected"}</span></span>
        <span><strong>Catalog</strong><span className="settings-overview-value">{catalogStatus ? `${catalogStatus.stock_count} stocks` : "Loading"}</span></span>
        <span><strong>App</strong><span className="settings-overview-value">v{appVersion || "..."}</span></span>
      </div>

      <SettingsSection id="ai" title="AI Analysis"
        description={`${providerDetails[provider].label} · ${status?.ai_configured ? "configured" : "not configured"}`}
        help="Configure the model provider used for analysis, its credentials or local endpoint, and the managed Include and Exclude phrases appended to the built-in analysis prompt."
        open={openSection === "ai"} onToggle={() => toggleSection("ai")}
        openInfoId={openInfoId} setOpenInfoId={setOpenInfoId}>
        <form className="settings-ai-form" onSubmit={save}>
          <label className="settings-field-provider">
            <SettingsLabel infoId="ai-provider" openInfoId={openInfoId} setOpenInfoId={setOpenInfoId}
              info={localProvider
                ? "Ollama runs the selected model on this computer. Install the model manually, then load an installed vision model from the Channels page."
                : "Cloud provider keys are encrypted and stored only on this computer. Choose the saved analysis model from the Channels page after configuring the provider."}>
              AI provider
            </SettingsLabel>
            <select value={provider} onChange={(e) => chooseProvider(e.target.value as AiProvider)}>
              <option value="ollama">Ollama Local - use a downloaded model</option>
              <option value="qwen">Qwen Cloud — default for Arabic and charts</option>
              <option value="openrouter">OpenRouter — free models available</option>
              <option value="huggingface">Hugging Face Inference Providers</option>
              <option value="openai">OpenAI</option>
            </select>
          </label>
          {!localProvider && <div className="credential-header settings-field-credentials">
            <div>
              <SettingsLabel infoId="provider-credentials" openInfoId={openInfoId} setOpenInfoId={setOpenInfoId}
                info="The API key is encrypted with the current Windows user account and stored locally. Replacing it changes only the selected provider credential.">
                <strong>{currentProvider.label}</strong>
              </SettingsLabel>
              <span>{status?.ai_provider === provider && status.ai_configured ? "API key saved" : "API key not configured"}</span>
            </div>
            <button type="button" className="secondary" onClick={replaceKey}>
              {editingProviderKey ? "Cancel" : status?.ai_provider === provider && status.ai_configured ? "Replace API key" : "Add API key"}
            </button>
          </div>}
          {editingProviderKey && !localProvider && (
            <label className="settings-field-api-key">
              <SettingsLabel infoId="new-provider-key" openInfoId={openInfoId} setOpenInfoId={setOpenInfoId}
                info={`Enter a new ${currentProvider.label} API key. It will be encrypted locally when settings are saved and is never displayed again.`}>
                {`New ${currentProvider.label} API key`}
              </SettingsLabel>
              <input type="password" autoComplete="new-password" placeholder={currentProvider.placeholder}
                value={(values[currentProvider.key!] as string) || ""}
                onChange={(e) => setValues((cur) => ({ ...cur, [currentProvider.key!]: e.target.value }))} required />
            </label>
          )}
          {localProvider && (
            <label className="settings-field-endpoint">
              <SettingsLabel infoId="ollama-url" openInfoId={openInfoId} setOpenInfoId={setOpenInfoId}
                info="Address of the Ollama service on this computer. The default is http://127.0.0.1:11434. Telegram data remains local while Ollama is used.">
                Ollama local service URL
              </SettingsLabel>
              <input type="url" value={values.ollama_base_url || "http://127.0.0.1:11434"}
                onChange={(e) => setValues((cur) => ({ ...cur, ollama_base_url: e.target.value }))} required />
            </label>
          )}
          {provider === "qwen" && (
            <label className="settings-field-endpoint">
              <SettingsLabel infoId="qwen-endpoint" openInfoId={openInfoId} setOpenInfoId={setOpenInfoId}
                info="Select the Qwen Model Studio endpoint from the same region and pay-as-you-go billing plan as the saved API key.">
                Qwen Cloud endpoint
              </SettingsLabel>
              <input type="url" list="qwen-endpoints"
                value={values.qwen_base_url || "https://dashscope.aliyuncs.com/compatible-mode/v1"}
                onChange={(e) => setValues((cur) => ({ ...cur, qwen_base_url: e.target.value }))} required />
              <datalist id="qwen-endpoints">
                <option value="https://dashscope.aliyuncs.com/compatible-mode/v1">China (Beijing)</option>
                <option value="https://dashscope-intl.aliyuncs.com/compatible-mode/v1">Singapore</option>
                <option value="https://dashscope-us.aliyuncs.com/compatible-mode/v1">US (Virginia)</option>
              </datalist>
            </label>
          )}
          <label className="prompt-phrase-field settings-field-include">
            <span className="prompt-phrase-label">
              <span className="prompt-phrase-name">
                <span>Include recommendation phrases</span>
                <SettingsInfo id="include-phrases" title="Include recommendation phrases"
                  text="Enter Arabic or English phrases separated by Arabic or English commas. They extend recommendation recognition without replacing the built-in stock identity, date, source, and output rules."
                  openInfoId={openInfoId} setOpenInfoId={setOpenInfoId} />
              </span>
              <small>{effectiveIncludePhrases.length} active</small>
            </span>
            <textarea
              value={values.analysis_include_phrases || ""}
              onChange={(e) => setValues((cur) => ({ ...cur, analysis_include_phrases: e.target.value }))}
              placeholder="سهم تحت المراقبة، أسهم مرشحة T+1، الشراء باختراق"
              rows={4}
            />
          </label>
          <label className="prompt-phrase-field settings-field-exclude">
            <span className="prompt-phrase-label">
              <span className="prompt-phrase-name">
                <span>Exclude recommendation phrases</span>
                <SettingsInfo id="exclude-phrases" title="Exclude recommendation phrases"
                  text="Matching content is excluded from recommendations. Exclude phrases take priority when the same phrase appears in both boxes."
                  openInfoId={openInfoId} setOpenInfoId={setOpenInfoId} />
              </span>
              <small>{excludePhrases.length} active</small>
            </span>
            <textarea
              value={values.analysis_exclude_phrases || ""}
              onChange={(e) => setValues((cur) => ({ ...cur, analysis_exclude_phrases: e.target.value }))}
              placeholder="الأسهم الأكثر سيولة، توصية سابقة، تم تحقيق المستهدف"
              rows={4}
            />
          </label>
          {conflictingPhrases.length > 0 && (
            <div className="prompt-guidance-alert warning">
              <Icon name="warning" />
              <span>These phrases appear in both boxes and will be excluded: <strong>{conflictingPhrases.join("، ")}</strong></span>
            </div>
          )}
          {promptPhrasesDirty && (
            <div className="prompt-guidance-alert unsaved">
              <Icon name="info" />
              <span>Phrase changes are not active yet. Press Save settings to apply them permanently.</span>
            </div>
          )}
          <div className="prompt-guidance-preview">
            <div className="settings-inline-heading">
              <strong>Active phrase section preview</strong>
              <SettingsInfo id="phrase-preview" title="Active phrase section preview"
                text="This managed section is appended to the existing prompt and does not replace it. Phrase guidance influences the model, but a recommendation must still identify a stock and satisfy the existing date rules."
                openInfoId={openInfoId} setOpenInfoId={setOpenInfoId} />
            </div>
            <pre>{promptPreview}</pre>
          </div>
          <div className="prompt-customization-history">
            <div className="prompt-customization-heading">
              <div>
                <span className="settings-inline-heading">
                  <strong>Prompt change log</strong>
                  <SettingsInfo id="prompt-history" title="Prompt change log"
                    text="Permanent local history of phrase additions, removals, resets, and restores. Restore reapplies a historical phrase configuration and records the action."
                    openInfoId={openInfoId} setOpenInfoId={setOpenInfoId} />
                </span>
                {(status?.prompt_customization_history_total ?? 0) > (status?.prompt_customization_history.length ?? 0)
                  && <span>Latest {status?.prompt_customization_history.length} of {status?.prompt_customization_history_total} entries</span>}
              </div>
              <button type="button" className="secondary" onClick={resetPrompt} disabled={saving || resettingPrompt}>
                <Icon name="refresh" /> {resettingPrompt ? "Resetting…" : "Reset to default prompt"}
              </button>
            </div>
            {status?.prompt_customization_error && (
              <div className="prompt-guidance-alert error">
                <Icon name="warning" />
                <span>{status.prompt_customization_error} The Reset button will preserve the damaged file as a local backup before recovery.</span>
              </div>
            )}
            {status?.prompt_customization_history?.length ? (
              <div className="prompt-history-list">
                {[...status.prompt_customization_history].reverse().map((entry) => (
                  <div className="prompt-history-entry" key={`${entry.history_index}-${entry.timestamp}`}>
                    <div className="prompt-history-entry-heading">
                      <div>
                        <strong>{entry.action === "reset" ? "Reset to default" : entry.action === "restored" ? "Configuration restored" : "Phrase guidance updated"}</strong>
                        <span>{formatCairoDateTime(entry.timestamp)}</span>
                      </div>
                      <button type="button" className="secondary compact" onClick={() => restorePrompt(entry.history_index, entry.timestamp)}
                        disabled={saving || resettingPrompt || restoringPromptIndex !== null}>
                        <Icon name="history" size={14} /> {restoringPromptIndex === entry.history_index ? "Restoring…" : "Restore"}
                      </button>
                    </div>
                    {entry.include_added.length > 0 && <small>Include added: {entry.include_added.join("، ")}</small>}
                    {entry.include_removed.length > 0 && <small>Include removed: {entry.include_removed.join("، ")}</small>}
                    {entry.exclude_added.length > 0 && <small>Exclude added: {entry.exclude_added.join("، ")}</small>}
                    {entry.exclude_removed.length > 0 && <small>Exclude removed: {entry.exclude_removed.join("، ")}</small>}
                    {entry.recovered_corrupt_file && <small>Recovered damaged file: {entry.recovered_corrupt_file}</small>}
                  </div>
                ))}
              </div>
            ) : <p className="empty">No prompt customizations have been recorded.</p>}
          </div>
          <div className="settings-save-bar">
            <button disabled={saving}>{saving ? "Saving…" : "Save settings"}</button>
          </div>
        </form>
      </SettingsSection>

      <SettingsSection id="telegram" title="Telegram"
        description={status?.telegram_configured ? (status.telegram_authorized ? "Connected" : "Credentials saved — not authorized") : "Not configured"}
        help="Configure the Telegram application credentials stored on this computer, authorize the account, and manually check active chats for recent messages."
        open={openSection === "telegram"} onToggle={() => toggleSection("telegram")}
        openInfoId={openInfoId} setOpenInfoId={setOpenInfoId}>
        <form onSubmit={save}>
          <div className="credential-header">
            <div>
              <SettingsLabel infoId="telegram-credentials" openInfoId={openInfoId} setOpenInfoId={setOpenInfoId}
                info="Telegram API ID and API hash come from my.telegram.org and are encrypted locally. Replacing them signs this computer out, so Telegram authorization must be completed again.">
                <strong>Telegram credentials</strong>
              </SettingsLabel>
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
                <SettingsLabel infoId="telegram-api-id" openInfoId={openInfoId} setOpenInfoId={setOpenInfoId}
                  info="Numeric application ID created for this account at my.telegram.org.">
                  New Telegram API ID
                </SettingsLabel>
                <input type="number" placeholder="From my.telegram.org"
                  value={values.telegram_api_id || ""}
                  onChange={(e) => setValues((cur) => ({ ...cur, telegram_api_id: Number(e.target.value) || undefined }))} required />
              </label>
              <label>
                <SettingsLabel infoId="telegram-api-hash" openInfoId={openInfoId} setOpenInfoId={setOpenInfoId}
                  info="Private application hash paired with the Telegram API ID at my.telegram.org. It is encrypted locally after saving.">
                  New Telegram API hash
                </SettingsLabel>
                <input type="password" autoComplete="new-password" placeholder="API hash"
                  value={values.telegram_api_hash || ""}
                  onChange={(e) => setValues((cur) => ({ ...cur, telegram_api_hash: e.target.value }))} required />
              </label>
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
            <div className="settings-inline-heading">
              <h3>Connect Telegram</h3>
              <SettingsInfo id="connect-telegram" title="Connect Telegram"
                text="Enter the phone number associated with the Telegram account. Telegram sends a login code that authorizes this computer for future app launches."
                openInfoId={openInfoId} setOpenInfoId={setOpenInfoId} />
            </div>
            <label>
              <SettingsLabel infoId="telegram-phone" openInfoId={openInfoId} setOpenInfoId={setOpenInfoId}
                info="Use the complete international number, including the country code, for example +201….">
                Phone number
              </SettingsLabel>
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
              <SettingsLabel infoId="telegram-code" openInfoId={openInfoId} setOpenInfoId={setOpenInfoId}
                info="Enter the one-time login code sent by Telegram. The code is used only for this authorization attempt and is not logged.">
                Verification code
              </SettingsLabel>
              <input value={code} onChange={(e) => setCode(e.target.value)} required />
            </label>
            <label>
              <SettingsLabel infoId="telegram-password" openInfoId={openInfoId} setOpenInfoId={setOpenInfoId}
                info="Required only when Telegram two-step verification is enabled. The password is used for authorization and is never logged.">
                Two-step password (only if enabled)
              </SettingsLabel>
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </label>
            <button disabled={verifying}>{verifying ? "Verifying…" : "Verify code"}</button>
          </form>
        )}

        {status?.telegram_authorized && (
          <div className="settings-subsection">
            <span className="settings-inline-heading">
              <strong>Fetch active channels now</strong>
              <SettingsInfo id="telegram-check" title="Fetch active channels now"
                text="Fetches recent messages only. It does not run AI analysis; use Channels when you are ready to analyze selected chats."
                openInfoId={openInfoId} setOpenInfoId={setOpenInfoId} />
            </span>
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

      <SettingsSection id="catalog" title="EGX Stock Catalog"
        description={catalogStatus ? `${catalogStatus.stock_count} stocks · refreshes every ${catalogStatus.refresh_days} days` : "Loading local stock mappings"}
        help="Maintains the local EGX stock catalog used to map ticker codes, Arabic names, English names, and learned aliases during analysis. Online refreshes occur only when due or when requested."
        open={openSection === "catalog"} onToggle={() => toggleSection("catalog")}
        openInfoId={openInfoId} setOpenInfoId={setOpenInfoId}>
        <div className="settings-subsection">
          <span className="settings-inline-heading">
            <strong>Arabic and English stock identities</strong>
            <SettingsInfo id="catalog-identities" title="Arabic and English stock identities"
              text="The catalog keeps ticker codes, Arabic names, English names, and learned aliases on this computer so results can use consistent stock identities."
              openInfoId={openInfoId} setOpenInfoId={setOpenInfoId} />
          </span>
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

      <SettingsSection id="application" title="Application" description={`Version ${appVersion || "Loading"}`}
        help="Check for signed EGX Analyzer releases. Installing an update replaces application files while keeping local settings, Telegram data, analysis history, and saved results."
        open={openSection === "updates"} onToggle={() => toggleSection("updates")}
        openInfoId={openInfoId} setOpenInfoId={setOpenInfoId}>
        <div className="settings-subsection">
          <span className="settings-inline-heading">
            <strong>Application updates</strong>
            <SettingsInfo id="application-updates" title="Application updates"
              text="Checks the configured release channel for a signed EGX Analyzer update. Local data and configuration remain unchanged."
              openInfoId={openInfoId} setOpenInfoId={setOpenInfoId} />
          </span>
          <button type="button" disabled={checkingUpdate} onClick={onCheckForUpdates}>
            {checkingUpdate ? "Checking…" : "Check for updates"}
          </button>
        </div>
      </SettingsSection>

      <SettingsSection id="diagnostics" title="Support and diagnostics" description="Local request logs and error traces"
        help="View local request results and error traces used for troubleshooting. API keys, Telegram codes, and passwords are never written to diagnostics."
        open={openSection === "diagnostics"} onToggle={() => toggleSection("diagnostics")}
        openInfoId={openInfoId} setOpenInfoId={setOpenInfoId}>
        {outputAudits.length > 0 && <div className="diagnostic-output-audits">
          <span className="settings-inline-heading">
            <strong>Model output audits</strong>
            <SettingsInfo id="model-output-audits" title="Model output audits"
              text="Non-blocking validation notices attached to saved model responses. They are retained for diagnostics and never change the returned model data."
              openInfoId={openInfoId} setOpenInfoId={setOpenInfoId} />
          </span>
          {outputAudits.map((item) => <div key={item.id} className="diagnostic-output-audit">
            <span>{formatGeneratedAt(item.generated_at)}</span>
            <p>{item.model_validation_warnings.join(" ")}</p>
          </div>)}
        </div>}
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
            `${entry.timestamp ? formatGeneratedAt(entry.timestamp) : ""} ${entry.level} ${entry.event} ${entry.method || ""} ${entry.path || ""} ${entry.status_code || ""} ${entry.error_type || ""}`
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
