# Prompt 1: FastAPI Backend + AWS CLI

Create a Python FastAPI backend in a `backend/` folder for the AI Cloud Cost Detective (AWS) project.

## What to build

- A FastAPI server with a `POST /api/analyze` endpoint that accepts
  `{ "region": "<aws-region>", "resource_group": "<name-or-null>" }`.
- A `GET /api/regions` endpoint that returns the list of AWS regions
  (`aws ec2 describe-regions --query 'Regions[].RegionName' -o json`).
- A `GET /api/resource-groups` endpoint that returns the list of AWS Resource Groups
  (`aws resource-groups list-groups -o json`). This is optional scoping — the primary
  unit is the region.
- Use Python's `subprocess` module to run AWS CLI commands:
  - `aws ec2 describe-regions` to list regions.
  - `aws resource-groups list-groups` to list resource groups.
  - `aws resourcegroupstaggingapi get-resources --region <region> -o json` to fetch all
    taggable resources in the selected region. If a resource group / tag filter is given,
    pass `--tag-filters`.
  - `aws ce get-cost-and-usage` for the last 30 days, `--granularity MONTHLY`,
    `--metrics UnblendedCost`, grouped by `Type=DIMENSION,Key=SERVICE` — to attach real
    spend to the scan.
- Parse the AWS CLI JSON output and return a structured response with: resource ARN,
  service, resource type, region, tags, and (where available) the matching monthly cost
  from Cost Explorer.
- Add error handling for AWS CLI not installed, no credentials configured
  (`Unable to locate credentials`), `AccessDenied`, an invalid region, and Cost Explorer
  not enabled.
- Enable CORS for `http://localhost:5173`.
- Include a `requirements.txt` with `fastapi`, `uvicorn`.

## Project structure

```
backend/
├── main.py
├── aws_scanner.py
├── requirements.txt
```

Refer to `Architecture.MD` and `RequestFlow.MD`. This covers step ③ of the request flow.
