import { useEffect, useState } from "react";
import {
  IconMenu2,
  IconSparkles,
  IconTerminal2,
  IconMessageQuestion,
  IconPlayerPlayFilled,
  IconCompass,
  IconBook2,
  IconSettings,
} from "@tabler/icons-react";
import { api, type QueryResult, type Health } from "./api";
import ResultsTable from "./components/ResultsTable";
import SchemaSidebar from "./components/SchemaSidebar";
import Guide from "./components/Guide";
import Config from "./components/Config";

const QUICK = [
  "show tables",
  "list databases",
  "database info",
  "row counts",
  "list schemas",
];

type View = "explorer" | "guide" | "config";
export type Mode = "ask" | "sql";

export default function App() {
  const [view, setView] = useState<View>("explorer");
  const [mode, setMode] = useState<Mode>("ask");
  const [useAI, setUseAI] = useState(false);
  const [input, setInput] = useState("show tables");
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [navOpen, setNavOpen] = useState(true);
  const [runId, setRunId] = useState(0); // bumps per query → remounts the results grid
  const [online, setOnline] = useState(true);

  // Heartbeat: poll health; if the browser can't reach the backend, the badge
  // flips to "connection lost" (the honest signal when the VPN/network drops).
  useEffect(() => {
    let fails = 0;
    const tick = async () => {
      try {
        setHealth(await api.health());
        setOnline(true);
        fails = 0;
      } catch {
        if (++fails >= 2) setOnline(false);
      }
    };
    tick();
    const id = window.setInterval(tick, 8000);
    return () => window.clearInterval(id);
  }, []);

  // Core executor — explicit params so callers don't fight React's async state.
  async function execute(value: string, m: Mode, ai: boolean) {
    value = value.trim();
    if (!value) return;
    setLoading(true);
    setError(null);
    try {
      let r: QueryResult;
      if (m === "sql") r = await api.query(value);
      else if (ai && health?.aiEnabled) r = await api.ai(value);
      else r = await api.ask(value);
      setResult(r);
      setRunId((n) => n + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  function run() {
    const v = input.trim();
    setInput(v);
    execute(v, mode, useAI);
  }

  function pick(question: string) {
    setView("explorer");
    setMode("ask");
    setInput(question);
    execute(question, "ask", useAI);
  }

  // From the Guide "Try it" buttons: set the controls, jump to Explorer, run.
  function tryExample(value: string, m: Mode, ai: boolean) {
    const withAI = ai && !!health?.aiEnabled;
    setView("explorer");
    setMode(m);
    setUseAI(withAI);
    setInput(value);
    execute(value, m, withAI);
  }

  const aiOn = useAI && !!health?.aiEnabled && mode === "ask";

  return (
    <div className="app">
      {/* ── Topbar ── */}
      <header className="topbar">
        <button className="nav-toggle" title="Toggle sidebar" onClick={() => setNavOpen((o) => !o)}>
          <IconMenu2 size={18} />
        </button>
        <div>
          <div className="page-name">
            {view === "guide" ? "Guide" : view === "config" ? "Configuration" : "Database Explorer"}
          </div>
          <div className="page-sub">
            {view === "guide"
              ? "How to use PG Connector"
              : view === "config"
              ? "Connect a database & manage AI settings"
              : "Ask questions about your PostgreSQL data"}
          </div>
        </div>
        <div className={`conn-badge ${!online ? "down" : health?.ok ? "up" : "down"}`}>
          {!online
            ? "● connection lost"
            : health?.ok
            ? `● ${health.database} @ ${health.host}`
            : "● not connected"}
        </div>
      </header>

      <div className="layout">
        {/* ── Sidebar ── */}
        {navOpen && (
          <nav className="sidebar">
            <div className="brand">
              <span className="brand-mark">Z</span>
              <div>
                <div className="brand-name">PG Connector</div>
                <div className="brand-sub">Zenlabs · PostgreSQL Explorer</div>
              </div>
            </div>

            <div className="nav-group">
              <div className="nav-group-label">Menu</div>
              <button
                className={"nav-item" + (view === "explorer" ? " active" : "")}
                onClick={() => setView("explorer")}
              >
                <IconCompass size={18} />
                <span className="label">Explorer</span>
              </button>
              <button
                className={"nav-item" + (view === "guide" ? " active" : "")}
                onClick={() => setView("guide")}
              >
                <IconBook2 size={18} />
                <span className="label">Guide</span>
              </button>
              <button
                className={"nav-item" + (view === "config" ? " active" : "")}
                onClick={() => setView("config")}
              >
                <IconSettings size={18} />
                <span className="label">Config</span>
              </button>
            </div>

            <SchemaSidebar onPick={pick} />
          </nav>
        )}

        {/* ── Main ── */}
        <main>
          <div className="page">
            {view === "guide" ? (
              <Guide aiEnabled={!!health?.aiEnabled} onTry={tryExample} />
            ) : view === "config" ? (
              <Config onSaved={() => api.health().then(setHealth).catch(() => {})} />
            ) : (
              <>
                <div className="card">
                  <div className="query-head">
                    <div className="segmented">
                      <button
                        className={mode === "ask" ? "active" : ""}
                        onClick={() => setMode("ask")}
                      >
                        <IconMessageQuestion size={15} style={{ verticalAlign: "-3px", marginRight: 5 }} />
                        Question
                      </button>
                      <button
                        className={mode === "sql" ? "active" : ""}
                        onClick={() => setMode("sql")}
                      >
                        <IconTerminal2 size={15} style={{ verticalAlign: "-3px", marginRight: 5 }} />
                        SQL
                      </button>
                    </div>

                    {mode === "ask" && health?.aiEnabled && (
                      <label className={`ai-toggle ${useAI ? "on" : ""}`}>
                        <input
                          type="checkbox"
                          checked={useAI}
                          onChange={(e) => setUseAI(e.target.checked)}
                        />
                        <IconSparkles size={15} />
                        AI (natural language)
                      </label>
                    )}
                    {mode === "ask" && !health?.aiEnabled && (
                      <span className="ai-hint">AI mode off — set LLM_ENABLED in backend .env to enable</span>
                    )}
                  </div>

                  <textarea
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) run();
                    }}
                    placeholder={
                      mode === "sql"
                        ? "SELECT * FROM ...   (read-only)"
                        : aiOn
                        ? "Ask anything, e.g. which project has the most error spans?"
                        : "e.g. columns in spans · count users · preview projects"
                    }
                    rows={mode === "sql" ? 4 : 2}
                    spellCheck={false}
                  />

                  <button className="run" onClick={() => run()} disabled={loading}>
                    <IconPlayerPlayFilled size={15} style={{ verticalAlign: "-2px", marginRight: 6 }} />
                    {loading ? "Running…" : "Run  (Ctrl+Enter)"}
                  </button>

                  <div className="quick">
                    <span className="label">Try:</span>
                    {QUICK.map((q) => (
                      <button key={q} className="filter-btn" onClick={() => pick(q)}>
                        {q}
                      </button>
                    ))}
                    <button className="filter-btn" onClick={() => setView("guide")}>
                      📖 open guide
                    </button>
                  </div>
                </div>

                {error && <div className="error-msg">{error}</div>}

                {result && (
                  <div className="card">
                    <div className="result-meta">
                      <span className="meta-pill">{(result.total ?? result.rowCount).toLocaleString()} rows</span>
                      <span className="meta-pill">{result.elapsedMs} ms</span>
                      <code title="SQL that ran">{result.sql}</code>
                    </div>
                    <ResultsTable key={runId} result={result} />
                  </div>
                )}

                {!result && !error && (
                  <div className="card">
                    <div className="center-state">
                      <div className="icon">🐘</div>
                      <h3>Ask your database a question</h3>
                      <p>
                        Pick a table on the left, try a suggestion, or open the{" "}
                        <a className="inline-link" onClick={() => setView("guide")}>Guide</a>.
                      </p>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
