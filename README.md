# AI Cloud Cost Detective (AWS)

![AWS](https://img.shields.io/badge/cloud-AWS-FF9900?logo=amazonwebservices&logoColor=white)
![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/frontend-React%20%2B%20Vite-61DAFB?logo=react&logoColor=black)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![OpenAI](https://img.shields.io/badge/AI-OpenAI%20gpt--4o-412991?logo=openai&logoColor=white)

An AI-powered tool that investigates AWS cloud costs automatically. It scans resources in an AWS account/region, pulls real spend data from AWS Cost Explorer, detects cost issues like over-provisioning and misconfigurations, and provides actionable suggestions with fixes.

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React (Vite + TypeScript + Tailwind) |
| Backend | Python (FastAPI) |
| Auth | Custom JWT Auth (bcrypt + PyJWT) |
| Cloud Data | AWS CLI (Resource Groups Tagging API + Cost Explorer) |
| Cloud | AWS |
| AI Analysis | OpenAI API *or* Amazon Bedrock (`LLM_PROVIDER`) |
| Database | Amazon RDS for PostgreSQL |
| Live Updates | FastAPI WebSocket |

## Architecture

```
                              ┌──────────────┐
                              │     USER     │
                              └──────┬───────┘
                                     │
                                     ▼
                           ┌───────────────────┐
                           │  REACT FRONTEND   │
                           └────────┬──────────┘
                                    :
                                    : Login / Signup
                                    ▼
                           ┌───────────────────┐
                           │  PYTHON BACKEND   │
                           │    (FastAPI)      │
                           │                   │
                           │  · Custom JWT Auth│
                           └───┬───────┬───┬───┘
                               :       :   :
                ┌──────────────┘       :   └──────────────┐
                :                      :                  :
                ▼                      ▼                  ▼
         ┌─────────────┐     ┌──────────────┐    ┌──────────────┐
         │   AWS CLI   │     │   FASTAPI    │    │   OPENAI     │
         │             │     │  WEBSOCKET   │    │    API       │
         │ tagging api │     │  (Progress)  │    │              │
         │ + cost expl.│     └──────┬───────┘    │ Cost Analysis│
         └──────┬──────┘            :            └──────┬───────┘
                :                   : Live updates      :
                ▼                   ▼                   :
         ┌─────────────┐   ┌───────────────┐            :
         │     AWS     │   │    REACT      │            :
         │  (Account / │   │  (Progress    │            :
         │   Region)   │   │   Tracker)    │            :
         └─────────────┘   └───────────────┘            :
                                                        ▼
                                                 ┌──────────────┐
                                                 │  AMAZON RDS  │
                                                 │  POSTGRESQL  │
                                                 │              │
                                                 │ · users      │
                                                 │ · analyses   │
                                                 └──────┬───────┘
                                                        :
                                                        : Stored results
                                                        ▼
                                                 ┌───────────────┐
                                                 │    REACT      │
                                                 │ (Final Report │
                                                 │  + Suggestions│
                                                 │  + Fixes)     │
                                                 └───────────────┘
```

## Request Flow

```
①  User ─·─·─► React ─·─·─► FastAPI Auth ─·─·─► JWT (RDS PostgreSQL)

②  User selects AWS Region (and optional Resource Group) ─·─·─► Python Backend

③  Python ─·─·─► AWS CLI ─·─·─► Fetches all resources + Cost Explorer spend

④  Python ─·─·─► FastAPI WebSocket ─·─·─► React (live progress)

⑤  Python ─·─·─► OpenAI API ─·─·─► Cost analysis

⑥  Python ─·─·─► RDS PostgreSQL ─·─·─► Stores analysis history

⑦  React ◄·─·─·─ Final report with suggestions & fixes
```

## What It Detects

- **Over-provisioned resources** — EC2 instances, RDS databases, or ECS/Fargate tasks sized larger than needed (cross-checked against Cost Explorer rightsizing recommendations)
- **Unused resources** — Unattached EBS volumes, unassociated Elastic IPs, idle load balancers (ALB/NLB/CLB), idle NAT gateways, old snapshots
- **Misconfigurations** — On-demand usage that should be Savings Plans / Reserved Instances, `gp2` volumes that should be `gp3`, missing instance auto-stop schedules
- **Storage & logging costs** — S3 buckets with no lifecycle policy, CloudWatch log groups with no retention (never expire), infrequently accessed data on Standard storage

## Prerequisites

- AWS CLI v2 installed and configured (`aws configure` or an `AWS_PROFILE`)
- An AWS account with credentials that allow read access to the Resource Groups Tagging API, Cost Explorer (`ce:Get*`), EC2/RDS/ELB/S3/CloudWatch Logs describe/list calls
- Cost Explorer enabled in the AWS Billing console (one-time, takes ~24h to populate)
- An Amazon RDS for PostgreSQL instance
- An OpenAI API key
- Python 3.10+
- Node.js 18+

## How to Run

### Docker (whole stack)

```bash
cp backend/.env.example backend/.env   # set JWT_SECRET + LLM settings
docker compose up --build
```

Frontend on `http://localhost:8080`, backend on `http://localhost:8000`. AWS
credentials are read from your shell env (`AWS_ACCESS_KEY_ID` / …) or from a
`~/.aws` bind mount you uncomment in `docker-compose.yml`.

### Backend (local)

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in your credentials
uvicorn main:app --reload
```

### Frontend (local)

```bash
cd frontend
npm install
npm run dev
```

## Configuration

Key environment variables (see `backend/.env.example` for the full list):

| Var | Purpose |
|---|---|
| `APP_ENV` | `development` / `production`. In `production` the app refuses to start with a default `JWT_SECRET` or a localhost `FRONTEND_ORIGIN`. |
| `LLM_PROVIDER` | `openai` (default) or `bedrock`. Bedrock keeps the scan payload inside your AWS account. |
| `BEDROCK_MODEL_ID` / `BEDROCK_REGION` | Model + region when `LLM_PROVIDER=bedrock`. |
| `ALLOW_SIGNUP` | Set `false` to disable self-service signup. |
| `SIGNUP_ALLOWED_DOMAINS` | Optional comma-separated email-domain allowlist for signup. |
| `FRONTEND_ORIGIN` | Comma-separated list of allowed browser origins (CORS). |
| `ANALYZE_RATE_LIMIT_PER_HOUR` / `ANALYZE_MAX_CONCURRENT_PER_USER` | Per-user analyze limits (per backend process). |
| `SCAN_ACCOUNTS` | Multi-account: `"<id>:<label>,…"` accounts shown in the UI picker. Empty = current account only. |
| `CROSS_ACCOUNT_ROLE_NAME` / `CROSS_ACCOUNT_EXTERNAL_ID` | Role assumed in each target account, and its trust-policy external id. |

The `/ws/progress/{id}` WebSocket requires a valid JWT (`?token=…`) and only
streams analyses owned by that user.

## How It Works

1. User signs up / logs in via custom JWT auth (credentials stored in RDS PostgreSQL)
2. Selects an AWS Region (and optionally an AWS Resource Group, and — if `SCAN_ACCOUNTS` is configured — a target account) to analyze
3. Python backend fetches all resources using the AWS CLI (Resource Groups Tagging API) and real spend from AWS Cost Explorer. For a non-default account it first assumes `CostDetectiveScanRole` there.
4. Live progress is streamed to the UI via FastAPI WebSocket
5. Resource + cost data is sent to OpenAI API for cost analysis
6. Analysis results are stored in RDS PostgreSQL
7. Final report with cost breakdown, suggestions, and fix commands (AWS CLI) is displayed

## IAM Permissions

Ready-to-apply policy documents and setup commands (single-account and
multi-account / AWS Organizations) are in [`infra/iam/`](infra/iam/); ECS/Fargate
task definitions are in [`infra/ecs/`](infra/ecs/). The credentials used by the
backend need a read-only policy. A minimal set:

```
tag:GetResources
ce:GetCostAndUsage
ce:GetRightsizingRecommendation
ce:GetSavingsPlansPurchaseRecommendation
resource-groups:ListGroups
resource-groups:ListGroupResources
ec2:DescribeInstances
ec2:DescribeVolumes
ec2:DescribeAddresses
ec2:DescribeSnapshots
ec2:DescribeRegions
ec2:DescribeNatGateways
elasticloadbalancing:DescribeLoadBalancers
elasticloadbalancing:DescribeTargetGroups
rds:DescribeDBInstances
s3:ListAllMyBuckets
s3:GetBucketLifecycleConfiguration
logs:DescribeLogGroups
```
