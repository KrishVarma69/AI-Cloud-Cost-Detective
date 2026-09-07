# IAM setup for the AI Cloud Cost Detective

All policies here are **read-only**. The tool never mutates an AWS account — the
"fix" commands in a report are shown to the user, not executed.

## Files

| File | Where it goes |
|---|---|
| `cost-detective-readonly-policy.json` | The permission policy the backend needs. Attach to the backend's task role. |
| `bedrock-invoke-policy.json` | Adds `bedrock:InvokeModel` for Anthropic models. Attach to the task role when `LLM_PROVIDER=bedrock`. |
| `ecs-task-trust-policy.json` | Trust policy for the ECS task role **and** the execution role. Replace `HUB_ACCOUNT_ID`. |
| `ecs-execution-role-policy.json` | Permissions for the ECS **execution** role: pull images, write logs, read `cost-detective/*` secrets. |
| `hub-assume-scan-roles-policy.json` | **Multi-account only.** Lets the backend's task role assume `CostDetectiveScanRole` in member accounts. |
| `member-account-scan-role-trust-policy.json` | **Multi-account only.** Trust policy for `CostDetectiveScanRole` in each member account. Replace `HUB_ACCOUNT_ID` and the external id. |

## Single account (start here)

```bash
aws iam create-policy \
  --policy-name CostDetectiveReadOnly \
  --policy-document file://cost-detective-readonly-policy.json

# If the backend runs on ECS/Fargate:
aws iam create-role \
  --role-name CostDetectiveTaskRole \
  --assume-role-policy-document file://ecs-task-trust-policy.json
aws iam attach-role-policy \
  --role-name CostDetectiveTaskRole \
  --policy-arn arn:aws:iam::HUB_ACCOUNT_ID:policy/CostDetectiveReadOnly
```

On EC2, attach `CostDetectiveReadOnly` to the instance profile instead. For
local dev, attach it to an IAM user and use `aws configure` / `AWS_PROFILE`.

**Also required, one-time:** enable **Cost Explorer** in the Billing console of
the **management (payer)** account. Data takes ~24h to populate. Cost Explorer
(`ce:*`) is global and pinned to `us-east-1` by the scanner.

## Multi-account (AWS Organizations)

This is **implemented**. You run the backend once in a **hub** account; it
assumes `CostDetectiveScanRole` in each **member** account for the duration of a
scan (`backend/aws_scanner.py`). Users pick the target account in the UI; the
list comes from the `SCAN_ACCOUNTS` env var.

Setup:

1. In each member account, create `CostDetectiveScanRole` with
   `member-account-scan-role-trust-policy.json` as its trust policy and
   `CostDetectiveReadOnly` attached. Deploy with CloudFormation StackSets across
   the org.
2. In the hub account, attach `hub-assume-scan-roles-policy.json` to
   `CostDetectiveTaskRole` (in addition to `CostDetectiveReadOnly`).
3. Pick one random **external id**, put it in every member trust policy, and set
   it on the backend as `CROSS_ACCOUNT_EXTERNAL_ID` (store as a secret).
4. Set `SCAN_ACCOUNTS=111122223333:Prod,444455556666:Dev` on the backend.
   `CROSS_ACCOUNT_ROLE_NAME` defaults to `CostDetectiveScanRole`.

Cost Explorer stays consolidated at the payer account, so spend figures are
org-wide regardless of which member account a scan targets.

Cost Explorer data is already consolidated at the payer account, so spend
figures are org-wide from there regardless of which member account is scanned.

## Notes on scope

- The `s3:*` statement is included because the README and the AI prompt mention
  S3 lifecycle checks, but `aws_scanner.py` does **not** call S3 yet. Harmless to
  grant; drop the statement if your security team prefers least-privilege-exact.
- No CloudWatch **metrics** permissions are granted. Idle detection here is
  structural (no target group, unattached, etc.), not utilisation-based. Add
  `cloudwatch:GetMetricData` if you later add utilisation checks.
