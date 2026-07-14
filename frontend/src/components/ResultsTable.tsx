import type { QueryResult } from "../api";

function cell(v: string | number | boolean | null) {
  if (v === null) return <span className="null">NULL</span>;
  if (typeof v === "boolean") return v ? "true" : "false";
  return String(v);
}

export default function ResultsTable({ result }: { result: QueryResult }) {
  if (result.columns.length === 0) {
    return <div className="muted">Statement executed. No rows returned.</div>;
  }
  return (
    <div className="table-wrap">
      <table className="link-table">
        <thead>
          <tr>
            <th className="rownum">#</th>
            {result.columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, i) => (
            <tr key={i}>
              <td className="rownum">{i + 1}</td>
              {row.map((v, j) => (
                <td key={j}>{cell(v)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
