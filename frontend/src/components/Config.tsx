import { useEffect, useState } from "react";
import {
  IconDatabase,
  IconSparkles,
  IconPlugConnected,
  IconDeviceFloppy,
  IconAlertTriangle,
  IconInfoCircle,
  IconCircleCheck,
  IconCircleX,
} from "@tabler/icons-react";
import { api, type AppConfig, type ConnStatus } from "../api";

const PROVIDERS = ["azure_openai", "openai", "groq", "gemini", "anthropic", "mock"];
const SSL_MODES = ["prefer", "require", "disable", "allow"];

type Live = { kind: "online"; data: ConnStatus } | { kind: "offline" } | { kind: "checking" };

// Poll the reachability probe. A failed fetch itself means the browser can't
// reach the backend (VNet/VPN dropped) -> "offline". Debounced (2 fails).
function useLiveStatus(pollMs = 7000): Live {
  const [s, setS] = useState<Live>({ kind: "checking" });
  useEffect(() => {
    let alive = true;
    let fails = 0;
    const tick = async () => {
      try {
        const d = await api.vpnStatus();
        if (!alive) return;
        fails = 0;
        setS({ kind: "online", data: d });
      } catch {
        if (alive && ++fails >= 2) setS({ kind: "offline" });
      }
    };
    tick();
    const id = window.setInterval(tick, pollMs);
    return () => { alive = false; window.clearInterval(id); };
  }, [pollMs]);
  return s;
}

function pillFor(live: Live): { cls: string; label: string } {
  if (live.kind === "checking") return { cls: "checking", label: "Checking connection…" };
  if (live.kind === "offline") return { cls: "bad", label: "Connection lost — can't reach the app (VPN / network down)" };
  const d = live.data;
  if (d.state === "n/a") return { cls: "na", label: "Local database — VPN not required" };
  if (d.state === "connected") return { cls: "ok", label: `Connected${d.latencyMs != null ? ` · ${d.latencyMs} ms` : ""}` };
  if (d.state === "unreachable") return { cls: "warn", label: `Unreachable — ${d.reason}` };
  return { cls: "bad", label: `Disconnected — ${d.reason}` };
}

type DbForm = { host: string; port: number; user: string; password: string; database: string; sslmode: string };
type LlmForm = {
  enabled: boolean; provider: string; model: string; apiKey: string;
  azureEndpoint: string; azureDeployment: string; azureApiVersion: string;
};

export default function Config({ onSaved }: { onSaved: () => void }) {
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [db, setDb] = useState<DbForm>({ host: "", port: 5432, user: "", password: "", database: "", sslmode: "prefer" });
  const [llm, setLlm] = useState<LlmForm>({ enabled: false, provider: "azure_openai", model: "", apiKey: "", azureEndpoint: "", azureDeployment: "", azureApiVersion: "2024-06-01" });
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dbResult, setDbResult] = useState<{ ok: boolean; title: string; detail?: string } | null>(null);
  const [testingLlm, setTestingLlm] = useState(false);
  const [savingLlm, setSavingLlm] = useState(false);
  const [llmResult, setLlmResult] = useState<{ ok: boolean; title: string; detail?: string } | null>(null);
  const live = useLiveStatus();
  const pill = pillFor(live);

  useEffect(() => {
    api.getConfig().then((c) => {
      setCfg(c);
      setDb({ host: c.db.host, port: c.db.port, user: c.db.user, password: "", database: c.db.database, sslmode: c.db.sslmode });
      setLlm({
        enabled: c.llm.enabled, provider: c.llm.provider, model: c.llm.model, apiKey: "",
        azureEndpoint: c.llm.azureEndpoint, azureDeployment: c.llm.azureDeployment, azureApiVersion: c.llm.azureApiVersion,
      });
    });
  }, []);

  async function testConn() {
    setTesting(true);
    setDbResult(null);
    try {
      const r = await api.testDb(db);
      setDbResult(
        r.ok
          ? { ok: true, title: `Connected to “${r.database}”`, detail: `${db.user}@${db.host}:${db.port}` }
          : { ok: false, title: "Connection failed", detail: r.error }
      );
    } catch (e) {
      setDbResult({ ok: false, title: "Connection failed", detail: e instanceof Error ? e.message : String(e) });
    } finally {
      setTesting(false);
    }
  }
  async function saveDb() {
    setSaving(true);
    setDbResult(null);
    try {
      const r = await api.saveDbConfig(db);
      setDbResult(
        r.ok
          ? { ok: true, title: `Saved — connected to “${r.database}”`, detail: `Now serving from ${db.user}@${db.host}:${db.port}` }
          : { ok: false, title: "Saved, but couldn't connect", detail: r.error }
      );
      setDb((d) => ({ ...d, password: "" }));
      onSaved();
    } catch (e) {
      setDbResult({ ok: false, title: "Save failed", detail: e instanceof Error ? e.message : String(e) });
    } finally {
      setSaving(false);
    }
  }
  async function testLlm() {
    setTestingLlm(true);
    setLlmResult(null);
    try {
      const r = await api.testLlm(llm);
      setLlmResult(
        r.ok
          ? { ok: true, title: `AI works — ${r.provider}${r.model ? ` · ${r.model}` : ""}`, detail: r.sql ? `Sample SQL: ${r.sql}` : undefined }
          : { ok: false, title: "AI test failed", detail: r.error }
      );
    } catch (e) {
      setLlmResult({ ok: false, title: "AI test failed", detail: e instanceof Error ? e.message : String(e) });
    } finally {
      setTestingLlm(false);
    }
  }
  async function saveLlm() {
    setSavingLlm(true);
    setLlmResult(null);
    try {
      const r = await api.saveLlmConfig(llm);
      setLlmResult(
        r.aiEnabled
          ? { ok: true, title: "Saved — AI is enabled" }
          : { ok: true, title: "Saved — AI is off", detail: "Enable it and add a key to use natural-language questions." }
      );
      setLlm((l) => ({ ...l, apiKey: "" }));
      onSaved();
    } catch (e) {
      setLlmResult({ ok: false, title: "Save failed", detail: e instanceof Error ? e.message : String(e) });
    } finally {
      setSavingLlm(false);
    }
  }

  if (!cfg) return <div className="card muted">Loading configuration…</div>;

  const pwPlaceholder = cfg.db.passwordSet ? "•••••••• (unchanged)" : "not set";
  const keyPlaceholder = cfg.llm.apiKeySet ? "•••••••• (unchanged)" : "not set";

  return (
    <div className="guide">
      {/* Connect / status card (Azure VPN note) */}
      <div className="card">
        <div className="guide-h"><IconPlugConnected size={17} style={{ verticalAlign: -3 }} /> Connection</div>
        <div className="status-row">
          <div className={"status-pill " + pill.cls}>
            <span className="dot" />
            {pill.label}
            <span className="live-tag">live</span>
          </div>
          <IconInfoCircle
            size={16}
            className="status-info"
            title="Live reachability + heartbeat — see the note below"
          />
        </div>
        <p className="status-explain">
          Live <b>reachability</b> check — can the app reach the database <b>right now</b>?
          (It's a connection test, not a direct read of your VPN.)<br />
          <b>Heartbeat:</b> the app pings the server every few seconds; if the pings fail,
          you've likely lost the VPN / network.
        </p>
        <p style={{ margin: "10px 0" }}>
          Pointed at <code>{cfg.db.host}</code> / <code>{cfg.db.database}</code>.
          {live.kind === "online" && live.data.mode === "in-vnet" &&
            " (Backend is in-VNet — this reflects the server's path, not your laptop's VPN.)"}
        </p>
        <div className="cfg-note">
          <IconAlertTriangle size={14} style={{ verticalAlign: -2 }} /> For the Azure database
          (<code>*.postgres.database.azure.com</code>), the corporate <b>VPN must be connected</b> —
          otherwise the host name won't resolve and the test above will fail.
        </div>
      </div>

      {/* Database config */}
      <div className="card">
        <div className="guide-h"><IconDatabase size={17} style={{ verticalAlign: -3 }} /> Database</div>
        <div className="guide-sub">Overrides the <code>.env</code> fallback. Saving reconnects the whole app live.</div>
        <div className="cfg-grid">
          <label className="cfg-field"><span>Host</span>
            <input value={db.host} onChange={(e) => setDb({ ...db, host: e.target.value })} /></label>
          <label className="cfg-field"><span>Port</span>
            <input type="number" value={db.port} onChange={(e) => setDb({ ...db, port: Number(e.target.value) })} /></label>
          <label className="cfg-field"><span>User</span>
            <input value={db.user} onChange={(e) => setDb({ ...db, user: e.target.value })} /></label>
          <label className="cfg-field"><span>Password</span>
            <input type="password" placeholder={pwPlaceholder} value={db.password} onChange={(e) => setDb({ ...db, password: e.target.value })} /></label>
          <label className="cfg-field"><span>Database</span>
            <input value={db.database} onChange={(e) => setDb({ ...db, database: e.target.value })} /></label>
          <label className="cfg-field"><span>SSL mode</span>
            <select value={db.sslmode} onChange={(e) => setDb({ ...db, sslmode: e.target.value })}>
              {SSL_MODES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select></label>
        </div>
        <div className="cfg-actions">
          <button className="rt-btn" disabled={testing || saving} onClick={testConn}>
            {testing ? "Testing…" : "Test"}
          </button>
          <button className="run" onClick={saveDb} disabled={saving || testing}>
            <IconDeviceFloppy size={15} style={{ verticalAlign: -3, marginRight: 5 }} />
            {saving ? "Saving…" : "Save & reconnect"}
          </button>
        </div>
        {dbResult && (
          <div className={"conn-result " + (dbResult.ok ? "ok" : "bad")}>
            {dbResult.ok ? <IconCircleCheck size={20} /> : <IconCircleX size={20} />}
            <div className="cr-body">
              <div className="cr-title">{dbResult.title}</div>
              {dbResult.detail && <div className="cr-detail">{dbResult.detail}</div>}
            </div>
          </div>
        )}
      </div>

      {/* LLM config */}
      <div className="card">
        <div className="guide-h"><IconSparkles size={17} style={{ verticalAlign: -3 }} /> AI / LLM</div>
        <div className="guide-sub">Overrides the <code>.env</code> fallback. Applies to the AI tick box immediately.</div>
        <label className="ai-toggle" style={{ marginBottom: 14 }}>
          <input type="checkbox" checked={llm.enabled} onChange={(e) => setLlm({ ...llm, enabled: e.target.checked })} />
          Enable AI (natural-language → SQL)
        </label>
        <div className="cfg-grid">
          <label className="cfg-field"><span>Provider</span>
            <select value={llm.provider} onChange={(e) => setLlm({ ...llm, provider: e.target.value })}>
              {PROVIDERS.map((p) => <option key={p} value={p}>{p}</option>)}
            </select></label>
          <label className="cfg-field"><span>Model</span>
            <input value={llm.model} onChange={(e) => setLlm({ ...llm, model: e.target.value })} placeholder="e.g. gpt-4o-mini" /></label>
          <label className="cfg-field"><span>API key</span>
            <input type="password" placeholder={keyPlaceholder} value={llm.apiKey} onChange={(e) => setLlm({ ...llm, apiKey: e.target.value })} /></label>
          {llm.provider === "azure_openai" && (
            <>
              <label className="cfg-field"><span>Azure endpoint</span>
                <input value={llm.azureEndpoint} onChange={(e) => setLlm({ ...llm, azureEndpoint: e.target.value })} placeholder="https://<resource>.openai.azure.com" /></label>
              <label className="cfg-field"><span>Azure deployment</span>
                <input value={llm.azureDeployment} onChange={(e) => setLlm({ ...llm, azureDeployment: e.target.value })} placeholder="your deployment name" /></label>
              <label className="cfg-field"><span>API version</span>
                <input value={llm.azureApiVersion} onChange={(e) => setLlm({ ...llm, azureApiVersion: e.target.value })} /></label>
            </>
          )}
        </div>
        <div className="cfg-actions">
          <button className="rt-btn" disabled={testingLlm || savingLlm} onClick={testLlm}>
            {testingLlm ? "Testing…" : "Test AI"}
          </button>
          <button className="run" onClick={saveLlm} disabled={savingLlm || testingLlm}>
            <IconDeviceFloppy size={15} style={{ verticalAlign: -3, marginRight: 5 }} />
            {savingLlm ? "Saving…" : "Save"}
          </button>
        </div>
        {llmResult && (
          <div className={"conn-result " + (llmResult.ok ? "ok" : "bad")}>
            {llmResult.ok ? <IconCircleCheck size={20} /> : <IconCircleX size={20} />}
            <div className="cr-body">
              <div className="cr-title">{llmResult.title}</div>
              {llmResult.detail && <div className="cr-detail">{llmResult.detail}</div>}
            </div>
          </div>
        )}
        <div className="cfg-note">
          <b>Test AI</b> tries your provider/model/key without saving — no restart needed.
          Model hints — groq: <code>llama-3.3-70b-versatile</code> · gemini: <code>gemini-2.5-flash</code> ·
          azure/openai: <code>gpt-4o-mini</code>. <code>mock</code> needs no key.
        </div>
      </div>
    </div>
  );
}
