import { useCallback, useEffect, useState } from "react";
import type { ApiClient, ChannelScore, Performance, ScoredRecommendation } from "./api";

const OUTCOME_LABELS: Record<string, string> = {
  target_1: "Target 1 hit",
  target_2: "Target 2 hit",
  stopped: "Stopped out",
  expired: "Expired",
  open: "Still open",
  entry_not_reached: "Entry never traded",
  ambiguous: "Ambiguous",
  unpriced: "No price data",
};

function outcomeTone(outcome: string): string {
  if (outcome === "target_1" || outcome === "target_2") return "good";
  if (outcome === "stopped") return "bad";
  if (outcome === "expired") return "warn";
  return "muted";
}

function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${value}%`;
}

function rate(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value}%`;
}

function entryRange(row: ScoredRecommendation): string {
  if (row.entry_low === null || row.entry_low === undefined) return "—";
  if (row.entry_high && row.entry_high !== row.entry_low) return `${row.entry_low} – ${row.entry_high}`;
  return String(row.entry_low);
}

export function Insights({
  api,
  showError,
  notify,
  windowSessions,
  onWindowChange,
  icon,
}: {
  api: ApiClient;
  showError: (message: string) => void;
  notify: (kind: "success" | "warning" | "error", text: string) => void;
  windowSessions: number;
  onWindowChange: (sessions: number) => void;
  icon: (name: "refresh") => JSX.Element;
}) {
  const [report, setReport] = useState<Performance | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(
    async (sessions: number) => {
      setLoading(true);
      try {
        setReport(await api.performance(sessions));
      } catch (error) {
        showError(error instanceof Error ? error.message : String(error));
      } finally {
        setLoading(false);
      }
    },
    [api, showError],
  );

  useEffect(() => {
    void load(windowSessions);
  }, [load, windowSessions]);

  const refreshPrices = async () => {
    setRefreshing(true);
    try {
      const result = await api.refreshPrices(windowSessions);
      const unpriced = result.unpriced?.length ?? 0;
      const summary =
        result.message ??
        `Priced ${result.priced ?? 0} of ${result.tickers} stocks over ${result.sessions_requested} sessions` +
          (unpriced ? ` · ${unpriced} have no price history` : "");
      notify(unpriced ? "warning" : "success", summary);
      await load(windowSessions);
    } catch (error) {
      showError(error instanceof Error ? error.message : String(error));
    } finally {
      setRefreshing(false);
    }
  };

  const totals = report?.totals;
  const counts = totals?.by_outcome ?? {};

  return (
    <section className="insights">
      <div className="insights-toolbar">
        <div className="insights-window">
          <label htmlFor="scoring-window">
            Scoring window
            <strong>
              {windowSessions} trading {windowSessions === 1 ? "session" : "sessions"}
            </strong>
          </label>
          <input
            id="scoring-window"
            type="range"
            min={1}
            max={30}
            value={windowSessions}
            disabled={loading || refreshing}
            onChange={(event) => onWindowChange(Number(event.target.value))}
          />
          <span className="insights-hint">
            How long a recommendation stays open before it counts as expired. Weekends and market
            holidays are not counted.
          </span>
        </div>
        <button type="button" className="secondary" onClick={refreshPrices} disabled={refreshing || loading}>
          {icon("refresh")} {refreshing ? "Fetching prices…" : "Refresh prices"}
        </button>
      </div>

      {loading && !report && <p className="empty">Scoring saved recommendations…</p>}

      {report && totals ? (
        <>
          <div className="insights-totals">
            <div className="insight-tile">
              <span className="insight-value">{rate(totals.hit_rate)}</span>
              <span className="insight-label">Hit rate</span>
            </div>
            <div className="insight-tile">
              <span className="insight-value">{totals.hits}</span>
              <span className="insight-label">Targets reached</span>
            </div>
            <div className="insight-tile">
              <span className="insight-value">{totals.judged}</span>
              <span className="insight-label">Calls judged</span>
            </div>
            <div className="insight-tile">
              <span className="insight-value">{totals.tracked}</span>
              <span className="insight-label">Calls tracked</span>
            </div>
          </div>

          <p className="insights-hint">
            {report.scoring_since
              ? `Scored from ${report.scoring_since}, the first session with stored prices.`
              : "No prices stored yet. Use Refresh prices to start scoring."}{" "}
            Only calls that could be judged count toward the hit rate: a stock with no price history,
            or one whose entry never traded, counts for nobody.
          </p>

          <div className="insights-outcomes">
            {Object.entries(OUTCOME_LABELS).map(([key, label]) => (
              <span key={key} className={`outcome-chip ${outcomeTone(key)}`}>
                {label}
                <strong>{counts[key] ?? 0}</strong>
              </span>
            ))}
          </div>

          <h3>Channels</h3>
          {report.channels.length === 0 ? (
            <p className="empty">No channel has a scored recommendation yet.</p>
          ) : (
            <div className="table">
              <table>
                <thead>
                  <tr>
                    <th>Channel</th>
                    <th className="numeric">Calls</th>
                    <th className="numeric">Judged</th>
                    <th className="numeric">Hits</th>
                    <th className="numeric">Hit rate</th>
                    <th className="numeric">Avg return</th>
                    <th className="numeric">Sessions to hit</th>
                    <th className="numeric">Stopped</th>
                    <th className="numeric">Not tradable</th>
                  </tr>
                </thead>
                <tbody>
                  {report.channels.map((row: ChannelScore) => (
                    <tr key={row.channel}>
                      <td>{row.channel}</td>
                      <td className="numeric">{row.calls}</td>
                      <td className="numeric">{row.judged}</td>
                      <td className="numeric">{row.hits}</td>
                      <td className="numeric">{rate(row.hit_rate)}</td>
                      <td className="numeric">{percent(row.average_return)}</td>
                      <td className="numeric">{row.median_sessions_to_hit ?? "—"}</td>
                      <td className="numeric">{row.stopped}</td>
                      <td className="numeric">{row.entry_not_reached + row.unpriced}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h3>Recommendations</h3>
          {report.recommendations.length === 0 ? (
            <p className="empty">Nothing scored yet.</p>
          ) : (
            <div className="table">
              <table>
                <thead>
                  <tr>
                    <th>Stock</th>
                    <th>Channel</th>
                    <th>Called</th>
                    <th>Outcome</th>
                    <th>Settled</th>
                    <th className="numeric">Entry</th>
                    <th className="numeric">Target</th>
                    <th className="numeric">Peak reached</th>
                    <th className="numeric">Return</th>
                  </tr>
                </thead>
                <tbody>
                  {report.recommendations.slice(0, 200).map((row, index) => (
                    <tr key={`${row.ticker}-${row.opened_on}-${index}`}>
                      <td>
                        <strong>{row.ticker}</strong>
                        {row.company_ar ? <span className="ar"> {row.company_ar}</span> : null}
                      </td>
                      <td>{row.channel}</td>
                      <td>{row.opened_on}</td>
                      <td>
                        <span className={`outcome-chip ${outcomeTone(row.outcome)}`}>
                          {OUTCOME_LABELS[row.outcome] ?? row.outcome}
                        </span>
                      </td>
                      <td>{row.settled_on ?? "—"}</td>
                      <td className="numeric">{entryRange(row)}</td>
                      <td className="numeric">{row.target ?? "—"}</td>
                      <td className="numeric">{row.peak_high ?? "—"}</td>
                      <td className="numeric">{percent(row.return_pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
