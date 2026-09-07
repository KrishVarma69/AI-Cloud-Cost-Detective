# ECS / Fargate deployment

Task definitions for running the stack on ECS Fargate behind an Application Load
Balancer. Replace every `HUB_ACCOUNT_ID` and the `example.com` / region values
before registering.

## Roles

| Role | Trust policy | Permissions |
|---|---|---|
| `CostDetectiveExecutionRole` | `infra/iam/ecs-task-trust-policy.json` | `infra/iam/ecs-execution-role-policy.json` (pull images, write logs, read `cost-detective/*` secrets) |
| `CostDetectiveTaskRole` | `infra/iam/ecs-task-trust-policy.json` | `infra/iam/cost-detective-readonly-policy.json` + `infra/iam/bedrock-invoke-policy.json` (+ `infra/iam/hub-assume-scan-roles-policy.json` for multi-account) |

## Secrets (AWS Secrets Manager)

```bash
aws secretsmanager create-secret --name cost-detective/jwt-secret \
  --secret-string "$(openssl rand -hex 48)"
aws secretsmanager create-secret --name cost-detective/database-url \
  --secret-string "postgresql://USER:PASS@your-db.rds.amazonaws.com:5432/costdetective?sslmode=require"
# Only if using multi-account scanning:
aws secretsmanager create-secret --name cost-detective/cross-account-external-id \
  --secret-string "$(openssl rand -hex 16)"
```

If you are **not** using multi-account scanning, delete the
`CROSS_ACCOUNT_EXTERNAL_ID` entry from `backend-task-definition.json`.

## Build & push images

```bash
AWS_ACCOUNT=HUB_ACCOUNT_ID
REGION=us-east-1
aws ecr get-login-password --region $REGION | docker login --username AWS \
  --password-stdin $AWS_ACCOUNT.dkr.ecr.$REGION.amazonaws.com

aws ecr create-repository --repository-name cost-detective-backend  || true
aws ecr create-repository --repository-name cost-detective-frontend || true

docker build -t $AWS_ACCOUNT.dkr.ecr.$REGION.amazonaws.com/cost-detective-backend:latest ./backend
docker push  $AWS_ACCOUNT.dkr.ecr.$REGION.amazonaws.com/cost-detective-backend:latest

docker build --build-arg VITE_API_BASE=https://api.cost-detective.example.com \
  -t $AWS_ACCOUNT.dkr.ecr.$REGION.amazonaws.com/cost-detective-frontend:latest ./frontend
docker push $AWS_ACCOUNT.dkr.ecr.$REGION.amazonaws.com/cost-detective-frontend:latest
```

## Register & run

```bash
aws ecs register-task-definition --cli-input-json file://infra/ecs/backend-task-definition.json
aws ecs register-task-definition --cli-input-json file://infra/ecs/frontend-task-definition.json

aws ecs create-cluster --cluster-name cost-detective

# One service per task family, each behind its own ALB target group.
aws ecs create-service --cluster cost-detective --service-name backend \
  --task-definition cost-detective-backend --desired-count 1 --launch-type FARGATE \
  --network-configuration 'awsvpcConfiguration={subnets=[subnet-xxxx],securityGroups=[sg-xxxx],assignPublicIp=DISABLED}' \
  --load-balancers 'targetGroupArn=arn:aws:elasticloadbalancing:...:targetgroup/cd-backend/xxxx,containerName=backend,containerPort=8000'
```

## Load balancer notes

- **Keep `desired-count` at 1 for the backend.** `ProgressHub` and the rate
  limiter are in-memory; a second task would not share them. The WebSocket also
  needs sticky routing. Scale out only after moving those to Redis + a queue.
- Enable **stickiness** on the backend target group and raise the idle timeout
  (WebSocket connections are long-lived).
- Route `/api/*` and `/ws/*` to the backend target group, everything else to the
  frontend target group — or host the frontend on S3 + CloudFront and point
  `VITE_API_BASE` at the backend ALB.
- Put the ALB behind your VPN/SSO or restrict its security group to office CIDRs
  for the pilot.
