export type Severity = "high" | "medium" | "low";

export type Issue = {
  resource: string;
  issue_type: "over-provisioned" | "unused" | "misconfigured" | string;
  severity: Severity;
  explanation: string;
  fix_command: string;
};

export type Report = {
  summary: string;
  estimated_monthly_savings: string;
  issues: Issue[];
  model?: string;
};

export type CostByService = { service: string; amount: number };

export type Account = { id: string; label: string };

export type Scan = {
  region: string;
  resource_group: string | null;
  account_id?: string | null;
  resource_count: number;
  scanned_at: string;
  cost: {
    available: boolean;
    currency?: string;
    current_month_to_date?: number;
    previous_month?: number | null;
    top_services?: CostByService[];
  };
  warnings?: string[];
};

export type AnalysisResult = {
  id?: string;
  scan: Scan;
  report: Report;
};

export type HistoryRow = {
  id: string;
  region: string;
  resource_group: string | null;
  account_id?: string | null;
  resources_scanned: number;
  issues_found: number;
  monthly_cost: number | null;
  estimated_savings: string | null;
  status: string;
  error: string | null;
  created_at: string;
};

export type AnalysisDetail = HistoryRow & {
  analysis_result: AnalysisResult | null;
};

export type ProgressMessage = {
  stage: string;
  message: string;
  pct: number;
  result?: AnalysisResult;
};
