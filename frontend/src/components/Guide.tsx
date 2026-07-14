import {
  IconMessageQuestion,
  IconSparkles,
  IconTerminal2,
  IconShieldCheck,
  IconTable,
  IconPlayerPlayFilled,
  IconInfoCircle,
} from "@tabler/icons-react";

type Mode = "ask" | "sql";

interface Props {
  aiEnabled: boolean;
  onTry: (value: string, mode: Mode, ai: boolean) => void;
}

const RULE_Q = [
  "show tables",
  "list databases",
  "list schemas",
  "row counts",
  "database info",
  "columns in spans",
  "count spans",
  "count users",
  "preview projects",
  "list projects",
];

const AI_Q = [
  "which project has the most spans",
  "what is the average span duration per project",
  "how many users are admins",
  "show the 5 longest running spans",
  "how many error spans are there per project",
];

const SQL_Q = [
  "SELECT * FROM projects",
  "SELECT id, name FROM projects",
  "SELECT * FROM spans WHERE status = 'ERROR'",
  "SELECT name, duration_ms FROM spans ORDER BY duration_ms DESC LIMIT 5",
  "SELECT count(*) AS total_spans FROM spans",
  "SELECT DISTINCT status FROM spans",
  "SELECT status, count(*) AS n FROM spans GROUP BY status ORDER BY n DESC",
  "SELECT project_id, round(avg(duration_ms)) AS avg_ms FROM spans GROUP BY project_id ORDER BY project_id",
  "SELECT p.name AS project, s.name AS span, s.status FROM projects p JOIN spans s ON s.project_id = p.id LIMIT 10",
  "SELECT * FROM users WHERE email LIKE '%zensar%'",
];

export default function Guide({ aiEnabled, onTry }: Props) {
  return (
    <div className="guide">
      {/* Intro */}
      <div className="card">
        <div className="guide-h">Welcome to PG Connector</div>
        <p>
          A read-only window into your PostgreSQL database. Ask in plain English,
          type SQL, or let AI translate a question into SQL for you — results
          always come back as a table. Nothing here can ever modify your data.
        </p>
      </div>

      {/* Three modes */}
      <div className="card">
        <div className="guide-h">Three ways to ask</div>
        <div className="table-wrap" style={{ maxHeight: "none" }}>
          <table className="link-table">
            <thead>
              <tr>
                <th>Mode</th>
                <th>Use it for</th>
                <th>Needs a key?</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><IconMessageQuestion size={14} style={{ verticalAlign: -2 }} /> Question</td>
                <td>Quick built-in questions: tables, columns, counts, previews</td>
                <td>No</td>
              </tr>
              <tr>
                <td><IconTerminal2 size={14} style={{ verticalAlign: -2 }} /> SQL</td>
                <td>You already know the SQL — full control</td>
                <td>No</td>
              </tr>
              <tr>
                <td><IconSparkles size={14} style={{ verticalAlign: -2 }} /> AI</td>
                <td>Any free-form question: joins, averages, filters, rankings</td>
                <td>Yes (Azure OpenAI / Groq…)</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* Question mode */}
      <div className="card">
        <div className="guide-h"><IconMessageQuestion size={17} style={{ verticalAlign: -3 }} /> Question mode — built-in questions</div>
        <div className="guide-sub">No AI needed. Click any to run it now.</div>
        <div className="chip-row">
          {RULE_Q.map((q) => (
            <button key={q} className="filter-btn" onClick={() => onTry(q, "ask", false)}>
              {q}
            </button>
          ))}
        </div>
        <p className="guide-sub" style={{ marginTop: 12, marginBottom: 0 }}>
          Also works: <code>columns in &lt;table&gt;</code>, <code>count &lt;table&gt;</code>,
          <code>preview &lt;table&gt;</code>, <code>describe &lt;table&gt;</code>.
        </p>
      </div>

      {/* AI mode */}
      <div className="card">
        <div className="guide-h"><IconSparkles size={17} style={{ verticalAlign: -3 }} /> AI mode — plain English → SQL</div>
        <div className="guide-sub">
          For questions the built-ins can't answer — joins, aggregates, rankings.
          {aiEnabled ? " Click any to run it now." : " (Enable AI in backend .env to try these.)"}
        </div>
        <div className="chip-row">
          {AI_Q.map((q) => (
            <button
              key={q}
              className="filter-btn"
              disabled={!aiEnabled}
              title={aiEnabled ? "Run with AI" : "AI is disabled"}
              onClick={() => onTry(q, "ask", true)}
            >
              {q}
            </button>
          ))}
        </div>
        {!aiEnabled && (
          <p className="guide-sub" style={{ marginTop: 12, marginBottom: 0 }}>
            <IconInfoCircle size={14} style={{ verticalAlign: -2 }} /> AI is currently off.
            Set <code>LLM_ENABLED=true</code> and a provider/key in <code>backend/.env</code>.
          </p>
        )}
      </div>

      {/* SQL mode */}
      <div className="card">
        <div className="guide-h"><IconTerminal2 size={17} style={{ verticalAlign: -3 }} /> SQL mode — 10 starter queries</div>
        <div className="guide-sub">Read-only. Click <b>Run</b> to open it in the Explorer.</div>
        {SQL_Q.map((sql) => (
          <div key={sql} className="sql-example">
            <code>{sql}</code>
            <button className="try-btn" onClick={() => onTry(sql, "sql", false)}>
              <IconPlayerPlayFilled size={12} /> Run
            </button>
          </div>
        ))}
      </div>

      {/* Safety */}
      <div className="card">
        <div className="guide-h"><IconShieldCheck size={17} style={{ verticalAlign: -3 }} /> Safety</div>
        <p style={{ marginBottom: 6 }}>
          This tool is <b>read-only</b> by design — two independent guards:
        </p>
        <ul className="guide-list">
          <li>Only <code>SELECT / WITH / SHOW / EXPLAIN</code> statements are accepted; anything that writes or changes schema is rejected before it runs.</li>
          <li>The database session itself is forced read-only, so even an unexpected write is blocked by PostgreSQL.</li>
          <li>A statement timeout and a row cap keep runaway queries in check.</li>
        </ul>
      </div>

      {/* Data */}
      <div className="card">
        <div className="guide-h"><IconTable size={17} style={{ verticalAlign: -3 }} /> Your data</div>
        <p style={{ marginBottom: 0 }}>
          Every table in the connected database is listed in the left panel. Click a
          table name to preview its rows, or <b>cols</b> to see its columns. To point
          the app at a different database, change the <code>PG*</code> values in{" "}
          <code>backend/.env</code> and restart — no code changes.
        </p>
      </div>
    </div>
  );
}
