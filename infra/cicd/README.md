# CI/CD — `.github/workflows/deploy.yml`

On push to `main` (or manual **Run workflow**): verify → build both images →
push to ECR → roll the ECS services. GitHub OIDC is used for AWS auth, so there
are **no AWS keys in GitHub**.

## One-time AWS setup

1. **GitHub OIDC provider** (once per account):

   ```bash
   aws iam create-open-id-connect-provider \
     --url https://token.actions.githubusercontent.com \
     --client-id-list sts.amazonaws.com
   ```

2. **Deploy role** the workflow assumes:

   ```bash
   aws iam create-role --role-name CostDetectiveGitHubDeploy \
     --assume-role-policy-document file://infra/iam/github-actions-oidc-trust-policy.json
   aws iam put-role-policy --role-name CostDetectiveGitHubDeploy \
     --policy-name deploy --policy-document file://infra/iam/github-actions-deploy-policy.json
   ```

   Edit `HUB_ACCOUNT_ID` and the `sub` (`repo:OWNER/REPO:ref:refs/heads/main`)
   in the trust policy first.

3. **Bootstrap the ECS services once** by hand (see `infra/ecs/README.md`). The
   workflow updates existing services from their *live* task definition — it
   does not create them.

## GitHub configuration

Repo → **Settings → Secrets and variables → Actions**.

### Secrets

| Name | Value |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | `arn:aws:iam::HUB_ACCOUNT_ID:role/CostDetectiveGitHubDeploy` |

### Variables

| Name | Example |
|---|---|
| `AWS_REGION` | `us-east-1` |
| `ECR_BACKEND_REPO` | `cost-detective-backend` |
| `ECR_FRONTEND_REPO` | `cost-detective-frontend` |
| `ECS_CLUSTER` | `cost-detective` |
| `ECS_BACKEND_SERVICE` | `backend` |
| `ECS_FRONTEND_SERVICE` | `frontend` |
| `ECS_BACKEND_TASK_FAMILY` | `cost-detective-backend` |
| `ECS_FRONTEND_TASK_FAMILY` | `cost-detective-frontend` |
| `VITE_API_BASE` | `https://api.cost-detective.example.com` |

## Notes

- The workflow pins `wait-for-service-stability: true`, so a failed rollout fails
  the run.
- Backend `desired-count` should stay at 1 (in-memory `ProgressHub` / rate
  limiter). The deploy still works at 1 replica.
- To change env vars or secrets on the running service, edit the task definition
  in AWS (or re-run `register-task-definition` from `infra/ecs/`); the workflow
  carries the live values forward and only swaps the image.
- Multi-account: also attach `infra/iam/hub-assume-scan-roles-policy.json` to
  `CostDetectiveTaskRole` (not the deploy role) and set `SCAN_ACCOUNTS` on the
  task definition.
