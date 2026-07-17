import { useEffect, useState } from "react";
import { IconTable } from "@tabler/icons-react";
import { api } from "../api";

interface Props {
  onPick: (question: string) => void;
  refreshKey?: number; // bump this to reload the table list (e.g. after DB config change)
}

// Lists tables as sidebar nav items; click previews rows, "cols" shows columns.
export default function SchemaSidebar({ onPick, refreshKey }: Props) {
  const [tables, setTables] = useState<{ schema: string; name: string }[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTables([]);
    setError(null);
    api
      .tables()
      .then((r) => {
        const iSchema = r.columns.indexOf("table_schema");
        const iName = r.columns.indexOf("table_name");
        setTables(
          r.rows.map((row) => ({
            schema: String(row[iSchema]),
            name: String(row[iName]),
          }))
        );
      })
      .catch((e) => setError(e.message));
  }, [refreshKey]);

  return (
    <div className="nav-group">
      <div className="nav-group-label">Tables</div>
      {error && <div className="muted">{error}</div>}
      {tables.length === 0 && !error && <div className="muted">Loading…</div>}
      {tables.map((t) => (
        <div key={`${t.schema}.${t.name}`} className="nav-item" onClick={() => onPick(`preview ${t.name}`)}>
          <IconTable size={18} />
          <span className="label" title={`${t.schema}.${t.name}`}>{t.name}</span>
          <button
            className="cols-chip"
            title="Show columns"
            onClick={(e) => {
              e.stopPropagation();
              onPick(`columns in ${t.name}`);
            }}
          >
            cols
          </button>
        </div>
      ))}
    </div>
  );
}
