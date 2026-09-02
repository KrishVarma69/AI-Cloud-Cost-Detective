import type { ProgressMessage } from "../types";

type Props = {
  steps: ProgressMessage[];
  done: boolean;
  error?: string | null;
};

export default function ProgressTracker({ steps, done, error }: Props) {
  const pct = steps.length ? steps[steps.length - 1].pct : 0;

  return (
    <div className="rounded-lg border border-white/10 bg-[#0d131a] p-5">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">Progress</h3>
        <span className="text-xs text-gray-500">{pct}%</span>
      </div>

      <div className="mb-4 h-1.5 w-full overflow-hidden rounded-full bg-white/10">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            error ? "bg-red-500" : "bg-brand"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>

      <ol className="space-y-2">
        {steps.map((s, i) => {
          const isLast = i === steps.length - 1;
          const isError = s.stage === "error";
          return (
            <li key={i} className="flex items-start gap-2 text-sm">
              <span
                className={`mt-0.5 inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] ${
                  isError
                    ? "bg-red-500/20 text-red-400"
                    : isLast && !done
                      ? "bg-brand/20 text-brand"
                      : "bg-emerald-500/20 text-emerald-400"
                }`}
              >
                {isError ? "!" : isLast && !done ? "…" : "✓"}
              </span>
              <span className={isError ? "text-red-400" : "text-gray-300"}>
                {s.message}
              </span>
            </li>
          );
        })}
      </ol>

      {error && (
        <p className="mt-4 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">
          {error}
        </p>
      )}
    </div>
  );
}
