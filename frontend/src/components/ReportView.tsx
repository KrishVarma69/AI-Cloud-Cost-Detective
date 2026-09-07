import { useState } from "react";
import type { AnalysisResult, Issue, Severity } from "../types";

const severityStyle: Record<Severity, string> = {
  high: "bg-red-500/15 text-red-400 border-red-500/30",
  medium: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30",
  low: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
};

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="rounded border border-white/10 px-2 py-1 text-[11px] text-gray-400 hover:bg-white/5"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function IssueCard({ issue }: { issue: Issue }) {
  const sev = (["high", "medium", "low"].includes(issue.severity)
    ? issue.severity
    : "low") as Severity;
  return (
    <div className="rounded-lg border border-white/10 bg-[#0d131a] p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span
          className={`rounded border px-2 py-0.5 text-[11px] font-semibold uppercase ${severityStyle[sev]}`}
        >
          {sev}
        </span>
        <span className="rounded bg-white/5 px-2 py-0.5 text-[11px] text-gray-400">
          {issue.issue_type}
        </span>
        <span className="font-mono text-xs text-gray-300">{issue.resource}</span>
      </div>
      <p className="text-sm text-gray-300">{issue.explanation}</p>
      {issue.fix_command && (
        <div className="mt-3 rounded-md border border-white/10 bg-[#0a0e13]">
          <div className="flex items-center justify-between border-b border-white/10 px-3 py-1.5">
            <span className="text-[11px] text-gray-500">fix</span>
            <CopyButton text={issue.fix_command} />
          </div>
          <pre className="overflow-x-auto px-3 py-2 text-xs text-emerald-300">
            <code>{issue.fix_command}</code>
          </pre>
        </div>
      )}
    </div>
  );
}

export default function ReportView({ data }: { data: AnalysisResult }) {
  const { scan, report } = data;
  const cost = scan.cost || { available: false };
  const currency = cost.currency || "USD";

  const bySeverity = { high: 0, medium: 0, low: 0 };
  for (const i of report.issues) {
    if (i.severity in bySeverity) bySeverity[i.severity as Severity]++;
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-4">
        <Stat label="Resources scanned" value={String(scan.resource_count)} />
        <Stat
          label="Monthly spend"
          value={
            cost.available && cost.current_month_to_date != null
              ? `${currency} ${cost.current_month_to_date.toLocaleString()}`
              : "n/a"
          }
          sub={
            cost.available && cost.previous_month != null
              ? `prev ${currency} ${cost.previous_month.toLocaleString()}`
              : undefined
          }
        />
        <Stat label="Issues found" value={String(report.issues.length)} sub={`${bySeverity.high} high · ${bySeverity.medium} med · ${bySeverity.low} low`} />
        <Stat label="Est. monthly savings" value={report.estimated_monthly_savings} accent />
      </div>

      {report.summary && (
        <div className="rounded-lg border border-white/10 bg-[#0d131a] p-4">
          <h3 className="mb-1 text-sm font-semibold text-white">Summary</h3>
          <p className="text-sm text-gray-300">{report.summary}</p>
          <p className="mt-2 text-[11px] text-gray-600">
            {scan.region}
            {scan.account_id ? ` · account: ${scan.account_id}` : ""}
            {scan.resource_group ? ` · group: ${scan.resource_group}` : ""} ·
            scanned {new Date(scan.scanned_at).toLocaleString()}
            {report.model ? ` · ${report.model}` : ""}
          </p>
        </div>
      )}

      {cost.available && cost.top_services && cost.top_services.length > 0 && (
        <div className="rounded-lg border border-white/10 bg-[#0d131a] p-4">
          <h3 className="mb-3 text-sm font-semibold text-white">
            Top services by spend
          </h3>
          <ul className="space-y-1.5">
            {cost.top_services.slice(0, 8).map((s) => (
              <li key={s.service} className="flex justify-between text-xs">
                <span className="text-gray-400">{s.service}</span>
                <span className="font-mono text-gray-300">
                  {currency} {s.amount.toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h3 className="mb-3 text-sm font-semibold text-white">
          Issues &amp; fixes
        </h3>
        {report.issues.length === 0 ? (
          <p className="rounded-lg border border-white/10 bg-[#0d131a] p-4 text-sm text-gray-400">
            No cost issues detected. 🎉
          </p>
        ) : (
          <div className="space-y-3">
            {report.issues.map((issue, i) => (
              <IssueCard key={i} issue={issue} />
            ))}
          </div>
        )}
      </div>

      {scan.warnings && scan.warnings.length > 0 && (
        <details className="rounded-lg border border-white/10 bg-[#0d131a] p-4 text-xs text-gray-500">
          <summary className="cursor-pointer text-gray-400">
            {scan.warnings.length} scan warning(s)
          </summary>
          <ul className="mt-2 space-y-1">
            {scan.warnings.map((w, i) => (
              <li key={i}>• {w}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: boolean;
}) {
  return (
    <div className="rounded-lg border border-white/10 bg-[#0d131a] p-4">
      <div className="text-[11px] uppercase tracking-wide text-gray-500">
        {label}
      </div>
      <div
        className={`mt-1 text-lg font-semibold ${
          accent ? "text-brand" : "text-white"
        }`}
      >
        {value}
      </div>
      {sub && <div className="mt-0.5 text-[11px] text-gray-600">{sub}</div>}
    </div>
  );
}
