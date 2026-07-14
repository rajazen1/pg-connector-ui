// Thin client for the FastAPI backend. All calls go through /api (proxied by Vite in dev).

export interface QueryResult {
  sql: string;
  columns: string[];
  rows: (string | number | boolean | null)[][];
  rowCount: number;
  truncated: boolean;
  elapsedMs: number;
}

export interface ApiError {
  error: string;
  sql?: string;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error((data as ApiError).error ?? `HTTP ${res.status}`);
  return data as T;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  const data = await res.json();
  if (!res.ok) throw new Error((data as ApiError).error ?? `HTTP ${res.status}`);
  return data as T;
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
  tables: () => get<QueryResult>("/api/tables"),
  health: () => get<Health>("/api/health"),
};
