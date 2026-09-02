## AI Cloud Cost Detective (AWS) - Request Flow

```
①  User ─·─·─► React ─·─·─► FastAPI Auth ─·─·─► JWT (RDS PostgreSQL)

②  User selects AWS Region (+ optional Resource Group) ─·─·─► Python Backend

③  Python ─·─·─► AWS CLI ─·─·─► Fetches all resources (Tagging API)
                          └─·─► Fetches spend + rightsizing (Cost Explorer)

④  Python ─·─·─► FastAPI WebSocket ─·─·─► React (live progress)

⑤  Python ─·─·─► OpenAI API ─·─·─► Cost analysis

⑥  Python ─·─·─► RDS PostgreSQL ─·─·─► Stores analysis history

⑦  React ◄·─·─·─ Final report with suggestions & fixes (AWS CLI commands)
```

## Stage detail

| # | Stage | AWS specifics |
|---|---|---|
| ① | **Auth** | `POST /api/auth/signup` / `login`, bcrypt hash, PyJWT token, stored in `users` (RDS PostgreSQL) |
| ② | **Scope selection** | `GET /api/regions` (from `aws ec2 describe-regions`) and `GET /api/resource-groups` (from `aws resource-groups list-groups`). User picks one region; resource group is an optional tag filter |
| ③ | **Scan** | `aws resourcegroupstaggingapi get-resources --region <r>` for inventory; `aws ce get-cost-and-usage` (last 30 days, grouped by `SERVICE` and `USAGE_TYPE`); `aws ce get-rightsizing-recommendation --service AmazonEC2`; `aws ec2 describe-volumes` / `describe-addresses` / `describe-snapshots`, `aws elbv2 describe-load-balancers`, `aws rds describe-db-instances`, `aws logs describe-log-groups`, `aws s3api get-bucket-lifecycle-configuration` for idle/misconfig checks |
| ④ | **Progress** | `ws://localhost:8000/ws/progress/{analysis_id}` — messages at each stage |
| ⑤ | **AI analysis** | Resources + cost breakdown + rightsizing hints → OpenAI `gpt-4o` → issues (severity), estimated savings, fix commands |
| ⑥ | **Persist** | Row in `analyses`: region, resource_group, resources_scanned, issues_found, estimated_savings, analysis_result (jsonb), monthly_cost, status |
| ⑦ | **Report** | Summary card + per-issue cards with copyable `aws ...` fix commands |
