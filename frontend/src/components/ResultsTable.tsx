import { useEffect, useRef, useState } from "react";
import { IconArrowUp, IconArrowDown, IconDownload, IconCopy } from "@tabler/icons-react";
import { api, type QueryResult } from "../api";

type Cell = string | number | boolean | null;
type Nav = { page: number; pageSize: number; sort: number | null; dir: "asc" | "desc"; filter: string };

const ROWNUM_W = 52;
const PAGE_SIZES = [50, 100, 250, 500];

function display(v: Cell) {
  if (v === null) return <span className="null">NULL</span>;
  if (typeof v === "boolean") return v ? "true" : "false";
  return String(v);
}
function csvEscape(v: Cell) {
  const s = v === null ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

// Server-driven grid. Page / sort / filter all run in PostgreSQL via /api/page.
// A single `nav` state drives one fetch-effect (with a cleanup guard so a stale
// response can never overwrite a newer one). App remounts this per query (key),
// so the first render already holds page 1 and we skip the initial refetch.
export default function ResultsTable({ result }: { result: QueryResult }) {
  const [view, setView] = useState<QueryResult>(result);
  const [nav, setNav] = useState<Nav>(() => ({
    page: result.page ?? 0,
    pageSize: result.pageSize ?? 100,
    sort: result.sortIdx ?? null,
    dir: result.sortDir ?? "asc",
    filter: result.filter ?? "",
  }));
  const [filterInput, setFilterInput] = useState(nav.filter);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [widths, setWidths] = useState<number[] | null>(null);
  const tableRef = useRef<HTMLTableElement>(null);
  const didResize = useRef(false);
  const filterTimer = useRef<number | undefined>(undefined);
  const first = useRef(true);

  // Fetch whenever nav changes — but not on the very first render (page 1 is
  // already in `view`). The cleanup marks a fetch stale if nav changes again.
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    let alive = true;
    setLoading(true);
    setErr(null);
    api
      .page(result.sql, { page: nav.page, pageSize: nav.pageSize, sort: nav.sort, dir: nav.dir, filter: nav.filter })
      .then((v) => alive && setView(v))
      .catch((e) => alive && setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nav]);

  const total = view.total ?? view.rowCount;
  const pageCount = Math.max(1, Math.ceil(total / nav.pageSize));
  const start = nav.page * nav.pageSize;

  function goPage(p: number) {
    setNav((n) => ({ ...n, page: Math.min(Math.max(0, p), pageCount - 1) }));
  }
  function changePageSize(ps: number) {
    setNav((n) => ({ ...n, pageSize: ps, page: 0 }));
  }
  function onSort(col0: number) {
    if (didResize.current) return;
    const idx = col0 + 1; // 1-based column position for SQL ORDER BY
    setNav((n) => {
      if (n.sort === idx) {
        if (n.dir === "asc") return { ...n, dir: "desc", page: 0 };
        return { ...n, sort: null, dir: "asc", page: 0 }; // asc -> desc -> off
      }
      return { ...n, sort: idx, dir: "asc", page: 0 };
    });
  }
  function onFilterInput(text: string) {
    setFilterInput(text);
    window.clearTimeout(filterTimer.current);
    filterTimer.current = window.setTimeout(() => setNav((n) => ({ ...n, filter: text, page: 0 })), 300);
  }

  // Column resize (snapshot widths on first drag, then adjust one column).
  function startResize(colIdx: number, e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    const ths = tableRef.current?.querySelectorAll("thead th");
    const base = widths ?? (ths ? [...ths].map((t) => (t as HTMLElement).offsetWidth) : []);
    if (!widths) setWidths(base);
    const startX = e.clientX;
    const startW = base[colIdx];
    function onMove(ev: MouseEvent) {
      didResize.current = true;
      const nw = Math.max(60, startW + (ev.clientX - startX));
      setWidths((prev) => {
        const arr = [...(prev ?? base)];
        arr[colIdx] = nw;
        return arr;
      });
    }
    function onUp() {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
      setTimeout(() => {
        didResize.current = false;
      }, 60);
    }
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  const firstLeft = widths ? widths[0] : ROWNUM_W;

  async function bulk(): Promise<QueryResult> {
    return api.page(result.sql, { page: 0, pageSize: 10000, sort: nav.sort, dir: nav.dir, filter: nav.filter });
  }
  async function exportCsv() {
    const v = await bulk();
    const lines = [v.columns.map(csvEscape).join(",")];
    for (const r of v.rows) lines.push(r.map(csvEscape).join(","));
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "query-result.csv";
    a.click();
    URL.revokeObjectURL(url);
  }
  async function copyTsv() {
    const v = await bulk();
    const lines = [v.columns.join("\t")];
    for (const r of v.rows) lines.push(r.map((c) => (c === null ? "" : String(c))).join("\t"));
    navigator.clipboard?.writeText(lines.join("\n"));
  }

  if (view.columns.length === 0) {
    return <div className="muted">Statement executed. No rows returned.</div>;
  }

  return (
    <div className="rt">
      <div className="rt-toolbar">
        <input
          className="rt-filter"
          placeholder="Filter (whole table, in SQL)…"
          value={filterInput}
          onChange={(e) => onFilterInput(e.target.value)}
        />
        <span className="rt-count">
          {loading ? "loading…" : `${total.toLocaleString()} rows${nav.filter ? " (filtered)" : ""}`}
        </span>
        <div className="rt-actions">
          <label className="rt-pagesize">
            Rows/page
            <select value={nav.pageSize} onChange={(e) => changePageSize(Number(e.target.value))}>
              {PAGE_SIZES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <button className="rt-btn" onClick={copyTsv} title="Copy (up to 10k rows, TSV)">
            <IconCopy size={14} /> Copy
          </button>
          <button className="rt-btn" onClick={exportCsv} title="Download CSV (up to 10k rows)">
            <IconDownload size={14} /> CSV
          </button>
        </div>
      </div>

      {err && <div className="error-msg">{err}</div>}

      <div className={"table-wrap" + (loading ? " loading" : "")}>
        <table
          className="link-table"
          ref={tableRef}
          style={{ tableLayout: widths ? "fixed" : "auto", width: widths ? widths.reduce((a, b) => a + b, 0) : undefined }}
        >
          {widths && (
            <colgroup>
              <col style={{ width: widths[0] }} />
              {view.columns.map((_, j) => (
                <col key={j} style={{ width: widths[j + 1] }} />
              ))}
            </colgroup>
          )}
          <thead>
            <tr>
              <th className="rownum frozen-num">#</th>
              {view.columns.map((c, j) => (
                <th
                  key={c}
                  className={"sortable" + (j === 0 ? " frozen-first" : "")}
                  style={j === 0 ? { left: firstLeft } : undefined}
                  onClick={() => onSort(j)}
                  title="Click to sort (in SQL) · drag right edge to resize"
                >
                  {c}
                  {nav.sort === j + 1 &&
                    (nav.dir === "asc" ? <IconArrowUp size={12} /> : <IconArrowDown size={12} />)}
                  <span
                    className="col-resize"
                    onMouseDown={(e) => startResize(j + 1, e)}
                    onClick={(e) => e.stopPropagation()}
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {view.rows.map((row, i) => (
              <tr key={start + i}>
                <td className="rownum frozen-num">{start + i + 1}</td>
                {row.map((v, j) => (
                  <td
                    key={j}
                    className={j === 0 ? "frozen-first" : ""}
                    style={j === 0 ? { left: firstLeft } : undefined}
                  >
                    {display(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {view.rows.length === 0 && !loading && (
          <div className="muted" style={{ padding: "14px" }}>
            No rows{nav.filter ? ` match “${nav.filter}”` : ""}.
          </div>
        )}
      </div>

      <div className="rt-pager">
        <button className="rt-btn" disabled={nav.page === 0 || loading} onClick={() => goPage(0)}>
          « First
        </button>
        <button className="rt-btn" disabled={nav.page === 0 || loading} onClick={() => goPage(nav.page - 1)}>
          ‹ Prev
        </button>
        <span className="rt-pageinfo">
          Page {nav.page + 1} of {pageCount.toLocaleString()}
        </span>
        <button className="rt-btn" disabled={nav.page >= pageCount - 1 || loading} onClick={() => goPage(nav.page + 1)}>
          Next ›
        </button>
        <button className="rt-btn" disabled={nav.page >= pageCount - 1 || loading} onClick={() => goPage(pageCount - 1)}>
          Last »
        </button>
      </div>
    </div>
  );
}
