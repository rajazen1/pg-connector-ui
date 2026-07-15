// Thin client for the FastAPI backend. All calls go through /api (proxied by Vite in dev).

export interface QueryResult {
  sql: string;
  columns: string[];
  rows: (string | number | boolean | null)[][];
  rowCount: number;
  truncated: boolean;
  elapsedMs: number;
  // server-side pagination (present on /api/query, /api/ask, /api/ai, /api/page)
  total?: number;
  page?: number;
  pageSize?: number;
  sortIdx?: number | null;
  sortDir?: "asc" | "desc";
  filter?: string;
}

export interface PageParams {
  page: number;
  pageSize: number;
  sort: number | null; // 1-based column position
  dir: "asc" | "desc";
  filter: string;
}

export interface ApiError {
  error: string;
  sql?: string;
}

// Parse a response defensively: read text, then try JSON. A gateway/ingress
// error (ACA 502/503/504 during a restart or rollout) returns an HTML page, so
// res.json() would throw a cryptic "Unexpected token '<'" and hide the real
// status. Fall back to the HTTP status line instead.
async function parse<T>(res: Response): Promise<T> {
  const text = await res.text();
  let data: unknown;
  try {
    data = text ? JSON.parse(text) : undefined;
  } catch {
    data = undefined; // non-JSON body (e.g. an ingress error page)
  }
  if (!res.ok) {
    const msg = (data as ApiError | undefined)?.error ?? `HTTP ${res.status} ${res.statusText}`.trim();
    throw new Error(msg);
  }
  return data as T;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parse<T>(res);
}

async function get<T>(path: string): Promise<T> {
  return parse<T>(await fetch(path));
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parse<T>(res);
}

export interface AppConfig {
  db: { host: string; port: number; user: string; database: string; sslmode: string; passwordSet: boolean };
  llm: {
    enabled: boolean; provider: string; model: string; apiKeySet: boolean;
    azureEndpoint: string; azureDeployment: string; azureApiVersion: string;
  };
}
export interface TestResult { ok: boolean; database?: string; version?: string; error?: string }
export interface LlmTestResult { ok: boolean; provider?: string; model?: string; sql?: string; error?: string }

export interface ConnStatus {
  mode: "local-db" | "vpn-gated" | "in-vnet";
  state: "connected" | "unreachable" | "disconnected" | "n/a";
  host: string;
  reason: string;
  latencyMs?: number | null;
  dnsOk?: boolean;
  tcpOk?: boolean;
}

export interface Health {
  ok: boolean;
  database: string;
  host: string;
  aiEnabled: boolean;
  aiProvider: string | null;
}

export const api = {
  ask: (question: string) => post<QueryResult>("/api/ask", { question }),
  ai: (question: string) => post<QueryResult>("/api/ai", { question }),
  query: (sql: string) => post<QueryResult>("/api/query", { sql }),
  page: (sql: string, p: PageParams) => post<QueryResult>("/api/page", { sql, ...p }),
  tables: () => get<QueryResult>("/api/tables"),
  health: () => get<Health>("/api/health"),
  vpnStatus: () => get<ConnStatus>("/api/vpn-status"),
  getConfig: () => get<AppConfig>("/api/config"),
  saveDbConfig: (v: Partial<AppConfig["db"]> & { password?: string }) =>
    put<{ saved: boolean; ok: boolean; database?: string; error?: string }>("/api/config/db", v),
  saveLlmConfig: (v: Partial<AppConfig["llm"]> & { apiKey?: string }) =>
    put<{ saved: boolean; aiEnabled: boolean }>("/api/config/llm", v),
  testDb: (v: Partial<AppConfig["db"]> & { password?: string }) =>
    post<TestResult>("/api/config/test-db", v),
  testLlm: (v: Partial<AppConfig["llm"]> & { apiKey?: string }) =>
    post<LlmTestResult>("/api/config/test-llm", v),
};
