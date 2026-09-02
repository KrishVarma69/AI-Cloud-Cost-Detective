import { useEffect, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import ReportView from "../components/ReportView";
import type { AnalysisDetail, AnalysisResult } from "../types";

export default function Report() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();
  const passed = (location.state as { result?: AnalysisResult } | null)?.result;

  const [data, setData] = useState<AnalysisResult | null>(passed ?? null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!passed);

  useEffect(() => {
    if (passed || !id) return;
    (async () => {
      try {
        const row = await api<AnalysisDetail>(`/api/analysis/${id}`);
        if (row.status === "failed") {
          setError(row.error || "This analysis failed.");
        } else if (row.analysis_result) {
          setData(row.analysis_result);
        } else {
          setError("This analysis is still running. Check back shortly.");
        }
      } catch (e) {
        setError(e instanceof ApiError ? e.message : "Failed to load analysis");
      } finally {
        setLoading(false);
      }
    })();
  }, [id, passed]);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-white">Analysis report</h1>
        <div className="flex gap-2 text-sm">
          <Link to="/history" className="text-gray-400 hover:text-white">
            History
          </Link>
          <span className="text-gray-700">·</span>
          <Link to="/" className="text-brand hover:underline">
            New analysis
          </Link>
        </div>
      </div>

      {loading && <p className="text-sm text-gray-400">Loading…</p>}
      {error && (
        <p className="rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </p>
      )}
      {data && <ReportView data={data} />}
    </div>
  );
}
