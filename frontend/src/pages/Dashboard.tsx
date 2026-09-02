import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, WS_BASE, getToken } from "../api";
import ProgressTracker from "../components/ProgressTracker";
import type { ProgressMessage } from "../types";

export default function Dashboard() {
  const navigate = useNavigate();

  const [regions, setRegions] = useState<string[]>([]);
  const [groups, setGroups] = useState<string[]>([]);
  const [region, setRegion] = useState("");
  const [group, setGroup] = useState("");
  const [loadErr, setLoadErr] = useState<string | null>(null);

  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<ProgressMessage[]>([]);
  const [done, setDone] = useState(false);
  const [runErr, setRunErr] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await api<{ regions: string[] }>("/api/regions");
        setRegions(r.regions);
        setRegion(r.regions.includes("us-east-1") ? "us-east-1" : r.regions[0] ?? "");
      } catch (e) {
        setLoadErr(e instanceof ApiError ? e.message : "Failed to load regions");
      }
      try {
        const g = await api<{ resource_groups: string[] }>("/api/resource-groups");
        setGroups(g.resource_groups);
      } catch {
        /* resource groups are optional */
      }
    })();
    return () => wsRef.current?.close();
  }, []);

  const canRun = useMemo(() => !!region && !running, [region, running]);

  async function run() {
    setRunning(true);
    setDone(false);
    setRunErr(null);
    setSteps([{ stage: "start", message: "Requesting analysis…", pct: 2 }]);

    try {
      const { analysis_id } = await api<{ analysis_id: string }>("/api/analyze", {
        method: "POST",
        body: { region, resource_group: group || null },
      });

      const token = getToken();
      const ws = new WebSocket(
        `${WS_BASE}/ws/progress/${analysis_id}?token=${token ?? ""}`,
      );
      wsRef.current = ws;

      ws.onmessage = (evt) => {
        const msg = JSON.parse(evt.data) as ProgressMessage;
        setSteps((prev) => [...prev, msg]);

        if (msg.stage === "complete") {
          setDone(true);
          setRunning(false);
          ws.close();
          navigate(`/report/${analysis_id}`, {
            state: { result: msg.result },
          });
        } else if (msg.stage === "error") {
          setDone(true);
          setRunning(false);
          setRunErr(msg.message);
          ws.close();
        }
      };

      ws.onerror = () => {
        setRunErr("Lost connection to the progress stream.");
        setRunning(false);
      };
    } catch (e) {
      setRunErr(e instanceof ApiError ? e.message : "Failed to start analysis");
      setRunning(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-white">Run a cost analysis</h1>
        <p className="mt-1 text-sm text-gray-500">
          Pick an AWS region (and optionally narrow to a Resource Group). The
          backend scans resources, pulls spend from Cost Explorer, and asks the
          AI for optimizations.
        </p>
      </div>

      {loadErr && (
        <p className="rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {loadErr}
        </p>
      )}

      <div className="grid gap-4 rounded-lg border border-white/10 bg-[#0d131a] p-5 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-xs text-gray-400">AWS Region</span>
          <select
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            className="w-full rounded-md border border-white/10 bg-[#111820] px-3 py-2 text-sm text-white outline-none focus:border-brand"
          >
            {regions.length === 0 && <option value="">Loading…</option>}
            {regions.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="mb-1 block text-xs text-gray-400">
            Resource Group <span className="text-gray-600">(optional)</span>
          </span>
          <select
            value={group}
            onChange={(e) => setGroup(e.target.value)}
            className="w-full rounded-md border border-white/10 bg-[#111820] px-3 py-2 text-sm text-white outline-none focus:border-brand"
          >
            <option value="">Whole region</option>
            {groups.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
        </label>

        <div className="sm:col-span-2">
          <button
            onClick={run}
            disabled={!canRun}
            className="rounded-md bg-brand px-5 py-2 text-sm font-semibold text-black transition-colors hover:bg-brand-dark disabled:opacity-50"
          >
            {running ? "Analyzing…" : "Run Analysis"}
          </button>
        </div>
      </div>

      {steps.length > 0 && (
        <ProgressTracker steps={steps} done={done} error={runErr} />
      )}
    </div>
  );
}
