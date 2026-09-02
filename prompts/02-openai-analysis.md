# Prompt 2: OpenAI API Integration for Cost Analysis

Build on top of the existing FastAPI backend. Add AI-powered cost analysis using the OpenAI API directly.

## What to build

- Create an `ai_analyzer.py` module in `backend/` that:
  - Takes the list of AWS resources and the Cost Explorer spend breakdown (from
    `aws_scanner.py`) as input.
  - Builds a prompt asking the AI to analyze the resources for: over-provisioning
    (EC2 / RDS / ECS-Fargate), unused/idle resources (unattached EBS volumes,
    unassociated Elastic IPs, idle ALB/NLB/CLB, idle NAT gateways, stale snapshots),
    misconfigurations (on-demand vs Savings Plans / Reserved Instances, `gp2` vs `gp3`,
    missing auto-stop schedules), wrong storage classes / tiers, and general cost
    optimization opportunities.
  - Passes along the AWS Cost Explorer rightsizing recommendation
    (`aws ce get-rightsizing-recommendation --service AmazonEC2`) and Savings Plans
    purchase recommendation as extra context so the AI can ground its estimates.
  - Calls the OpenAI chat completions API (`gpt-4o`) and returns the structured analysis.
- The AI response should include: a summary, list of issues found (with severity:
  high/medium/low), estimated monthly savings, and actionable fix commands — **AWS CLI**
  commands the user can run (e.g. `aws ec2 delete-volume`, `aws ec2 release-address`,
  `aws ec2 modify-instance-attribute`, `aws ec2 modify-volume --volume-type gp3`,
  `aws s3api put-bucket-lifecycle-configuration`, `aws logs put-retention-policy`).
- Update `POST /api/analyze` to call `aws_scanner` first, then pass results to
  `ai_analyzer`, and return the final analysis.
- Store the OpenAI API key in environment variables. Add a `.env.example` file.
- Update `requirements.txt` — add `openai`, `python-dotenv`.

## Project structure update

```
backend/
├── main.py          (updated)
├── aws_scanner.py   (no change)
├── ai_analyzer.py   (new)
├── requirements.txt (updated)
├── .env.example     (new — OPENAI_API_KEY)
```

Refer to `Architecture.MD` and `RequestFlow.MD`. This covers step ⑤ of the request flow.
