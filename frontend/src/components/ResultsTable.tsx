import { useEffect, useMemo, useRef, useState } from "react";
import { IconArrowUp, IconArrowDown, IconDownload, IconCopy } from "@tabler/icons-react";
import type { QueryResult } from "../api";

type Cell = string | number | boolean | null;

const ROWNUM_W = 52;

function display(v: Cell) {
  if (v === null) return <span className="null">NULL</span>;
  if (typeof v === "boolean") return v ? "true" : "false";
  return String(v);
}

// Numeric-aware comparison; NULLs sort first.
function compare(a: Cell, b: Cell): number {
  if (a === null && b === null) return 0;
  if (a === null) return -1;
  if (b === null) return 1;
  const na = Number(a);
  const nb = Number(b);
  const aNum = a !== "" && !Number.isNaN(na);
  const bNum = b !== "" && !Number.isNaN(nb);
  if (aNum && bNum) return na - nb;
  return String(a).localeCompare(String(b));
}

const PAGE_SIZES = [25, 50, 100, 0]; // 0 = All

export default function ResultsTable({ result }: { result: QueryResult }) {
  const [filter, setFilter] = useState("");
  const [sortCol, setSortCol] = useState<number | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [pageSize, setPageSize] = useState(50);
  const [page, setPage] = useState(0);
  // Explicit column widths [rownum, ...dataCols]; null = auto layout until first resize.
  const [widths, setWidths] = useState<number[] | null>(null);
  const tableRef = useRef<HTMLTableElement>(null);
  const didResize = useRef(false);

  // Reset all view state whenever a new result arrives.
  useEffect(() => {
    setFilter("");
    setSortCol(null);
    setSortDir("asc");
    setPage(0);
    setWidths(null);
  }, [result]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return result.rows;
    return result.rows.filter((r) =>
      r.some((c) => (c === null ? "null" : String(c)).toLowerCase().includes(q))
    );
  }, [result.rows, filter]);

  const sorted = useMemo(() => {
    if (sortCol === null) return filtered;
    const dir = sortDir === "asc" ? 1 : -1;
    return [...filtered].sort((ra, rb) => dir * compare(ra[sortCol], rb[sortCol]));
  }, [filtered, sortCol, sortDir]);

  const total = result.rows.length;
  const size = pageSize === 0 ? sorted.length || 1 : pageSize;
  const pageCount = Math.max(1, Math.ceil(sorted.length / size));
  const clampedPage = Math.min(page, pageCount - 1);
  const start = clampedPage * size;
  const pageRows = sorted.slice(start, start + size);

  useEffect(() => {
    if (page > pageCount - 1) setPage(0);
  }, [pageCount, page]);

  function toggleSort(i: number) {
    if (didResize.current) return; // swallow only the click that ends a resize drag
    if (sortCol !== i) {
      setSortCol(i);
      setSortDir("asc");
    } else if (sortDir === "asc") {
      setSortDir("desc");
    } else {
      setSortCol(null);
    }
  }

  // Column resize: snapshot current widths on first drag, then adjust one column.
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
      // Clear the guard just after the click that this mouseup may trigger,
      // so later header clicks sort normally.
      setTimeout(() => {
        didResize.current = false;
      }, 60);
    }
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }

  const firstLeft = widths ? widths[0] : ROWNUM_W;

  function csvEscape(v: Cell) {
    const s = v === null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  }
  function exportCsv() {
    const lines = [result.columns.map(csvEscape).join(",")];
    for (const r of sorted) lines.push(r.map(csvEscape).join(","));
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "query-result.csv";
    a.click();
    URL.revokeObjectURL(url);
  }
  function copyTsv() {
    const lines = [result.columns.join("\t")];
    for (const r of sorted) lines.push(r.map((c) => (c === null ? "" : String(c))).join("\t"));
    navigator.clipboard?.writeText(lines.join("\n"));
  }

  if (result.columns.length === 0) {
    return <div className="muted">Statement executed. No rows returned.</div>;
  }

  return (
    <div className="rt">
      <div className="rt-toolbar">
        <input
          className="rt-filter"
          placeholder="Filter rows…"
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value);
            setPage(0);
          }}
        />
        <span className="rt-count">
          {sorted.length === total ? `${total} rows` : `${sorted.length} of ${total} rows`}
        </span>
        <div className="rt-actions">
          <label className="rt-pagesize">
            Rows/page
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(0);
              }}
            >
              {PAGE_SIZES.map((s) => (
                <option key={s} value={s}>
                  {s === 0 ? "All" : s}
                </option>
              ))}
            </select>
          </label>
          <button className="rt-btn" onClick={copyTsv} title="Copy all rows (TSV)">
            <IconCopy size={14} /> Copy
          </button>
          <button className="rt-btn" onClick={exportCsv} title="Download all rows as CSV">
            <IconDownload size={14} /> CSV
          </button>
        </div>
      </div>

      <div className="table-wrap">
        <table
          className="link-table"
          ref={tableRef}
          style={{ tableLayout: widths ? "fixed" : "auto", width: widths ? widths.reduce((a, b) => a + b, 0) : undefined }}
        >
          {widths && (
            <colgroup>
              <col style={{ width: widths[0] }} />
              {result.columns.map((_, j) => (
                <col key={j} style={{ width: widths[j + 1] }} />
              ))}
            </colgroup>
          )}
          <thead>
            <tr>
              <th className="rownum frozen-num">#</th>
              {result.columns.map((c, j) => (
                <th
                  key={c}
                  className={"sortable" + (j === 0 ? " frozen-first" : "")}
                  style={j === 0 ? { left: firstLeft } : undefined}
                  onClick={() => toggleSort(j)}
                  title="Click to sort · drag right edge to resize"
                >
                  {c}
                  {sortCol === j &&
                    (sortDir === "asc" ? <IconArrowUp size={12} /> : <IconArrowDown size={12} />)}
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
            {pageRows.map((row, i) => (
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
        {pageRows.length === 0 && (
          <div className="muted" style={{ padding: "14px" }}>
            No rows match “{filter}”.
          </div>
        )}
      </div>

      {pageCount > 1 && (
        <div className="rt-pager">
          <button className="rt-btn" disabled={clampedPage === 0} onClick={() => setPage(0)}>
            « First
          </button>
          <button className="rt-btn" disabled={clampedPage === 0} onClick={() => setPage(clampedPage - 1)}>
            ‹ Prev
          </button>
          <span className="rt-pageinfo">
            Page {clampedPage + 1} of {pageCount}
          </span>
          <button
            className="rt-btn"
            disabled={clampedPage >= pageCount - 1}
            onClick={() => setPage(clampedPage + 1)}
          >
            Next ›
          </button>
          <button
            className="rt-btn"
            disabled={clampedPage >= pageCount - 1}
            onClick={() => setPage(pageCount - 1)}
          >
            Last »
          </button>
        </div>
      )}
    </div>
  );
}
