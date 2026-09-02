# AI Cloud Cost Detective (AWS)

An AI-powered tool that investigates AWS cloud costs automatically. It scans resources in an AWS account/region, pulls real spend data from AWS Cost Explorer, detects cost issues like over-provisioning and misconfigurations, and provides actionable suggestions with fixes.

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React (Vite + TypeScript + Tailwind) |
| Backend | Python (FastAPI) |
| Auth | Custom JWT Auth (bcrypt + PyJWT) |
| Cloud Data | AWS CLI (Resource Groups Tagging API + Cost Explorer) |
| Cloud | AWS |
| AI Analysis | OpenAI API |
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

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in your credentials
uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## How It Works

1. User signs up / logs in via custom JWT auth (credentials stored in RDS PostgreSQL)
2. Selects an AWS Region (and optionally an AWS Resource Group) to analyze
3. Python backend fetches all resources using the AWS CLI (Resource Groups Tagging API) and real spend from AWS Cost Explorer
4. Live progress is streamed to the UI via FastAPI WebSocket
5. Resource + cost data is sent to OpenAI API for cost analysis
6. Analysis results are stored in RDS PostgreSQL
7. Final report with cost breakdown, suggestions, and fix commands (AWS CLI) is displayed

## IAM Permissions

The credentials used by the backend need a read-only policy. A minimal set:

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

The AI-suggested fix commands are **write** operations — run them yourself after review. The tool never executes them.
