import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api";
import type { HistoryRow } from "../types";

const statusStyle: Record<string, string> = {
  complete: "text-emerald-400",
  running: "text-yellow-400",
  failed: "text-red-400",
};

export default function History() {
  const [rows, setRows] = useState<HistoryRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await api<{ analyses: HistoryRow[] }>("/api/history");
        setRows(res.analyses);
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Failed to load history");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold text-white">Past analyses</h1>

      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && (
        <p className="rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </p>
      )}

      {!loading && !error && rows.length === 0 && (
        <p className="rounded-lg border border-white/10 bg-[#0d131a] p-4 text-sm text-gray-400">
          No analyses yet.{" "}
          <Link to="/" className="text-brand hover:underline">
            Run your first one.
          </Link>
        </p>
      )}

      {rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-white/10">
          <table className="w-full text-sm">
            <thead className="bg-[#0d131a] text-left text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-4 py-2.5">Region</th>
                <th className="px-4 py-2.5">Date</th>
                <th className="px-4 py-2.5">Resources</th>
                <th className="px-4 py-2.5">Issues</th>
                <th className="px-4 py-2.5">Monthly cost</th>
                <th className="px-4 py-2.5">Est. savings</th>
                <th className="px-4 py-2.5">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {rows.map((r) => (
                <tr key={r.id} className="hover:bg-white/5">
                  <td className="px-4 py-2.5">
                    <Link
                      to={`/report/${r.id}`}
                      className="text-brand hover:underline"
                    >
                      {r.region}
                    </Link>
                    {r.resource_group && (
                      <span className="ml-1 text-xs text-gray-600">
                        / {r.resource_group}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-gray-400">
                    {new Date(r.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-2.5 text-gray-300">
                    {r.resources_scanned}
                  </td>
                  <td className="px-4 py-2.5 text-gray-300">{r.issues_found}</td>
                  <td className="px-4 py-2.5 text-gray-300">
                    {r.monthly_cost != null
                      ? `$${r.monthly_cost.toLocaleString()}`
                      : "—"}
                  </td>
                  <td className="px-4 py-2.5 text-gray-300">
                    {r.estimated_savings || "—"}
                  </td>
                  <td
                    className={`px-4 py-2.5 ${statusStyle[r.status] ?? "text-gray-400"}`}
                  >
                    {r.status}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
