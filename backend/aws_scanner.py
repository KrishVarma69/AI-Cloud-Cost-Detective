"""AWS resource + cost scanner.

Shells out to the AWS CLI (v2) via subprocess, exactly as described in
`prompts/01-fastapi-aws-cli.md`. Every call is defensive: a single
``AccessDenied`` on one service degrades to a warning instead of failing the
whole scan.
"""
from __future__ import annotations

import contextvars
import json
import os
import shutil
import subprocess
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Optional

ProgressCb = Optional[Callable[[str, str, int], Any]]


class AwsError(RuntimeError):
    """Raised for problems we can explain to the user (no CLI, no creds, ...)."""


# ─────────────────────────────────────────────────────────────────────────────
# Cross-account support
#
# When a scan targets another AWS account, we assume `CROSS_ACCOUNT_ROLE_NAME`
# in that account and expose the temporary credentials to every `aws` subprocess
# via a ContextVar (set for the duration of one `scan_region` call).
# ─────────────────────────────────────────────────────────────────────────────
_aws_env: contextvars.ContextVar[Optional[dict[str, str]]] = contextvars.ContextVar(
    "_aws_env", default=None
)
_cred_cache: dict[str, dict[str, Any]] = {}


def list_accounts() -> list[dict[str, str]]:
    """Accounts offered in the UI picker.

    Configured via ``SCAN_ACCOUNTS`` — a comma-separated list of
    ``<account-id>`` or ``<account-id>:<label>`` entries. The ambient-credential
    account is always offered first as an empty id.
    """
    accounts = [{"id": "", "label": "This account (default credentials)"}]
    for entry in os.getenv("SCAN_ACCOUNTS", "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        acct, _, label = entry.partition(":")
        acct = acct.strip()
        if acct:
            accounts.append({"id": acct, "label": label.strip() or acct})
    return accounts


def _assume_role_env(account_id: str) -> dict[str, str]:
    """Return AWS_* env vars for a role in ``account_id``, cached until expiry."""
    now = datetime.now(timezone.utc)
    cached = _cred_cache.get(account_id)
    if cached and cached["expiry"] > now + timedelta(minutes=5):
        return cached["env"]

    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:  # pragma: no cover
        raise AwsError(
            "Cross-account scanning needs boto3. Add it to backend/requirements.txt."
        ) from exc

    role_name = os.getenv("CROSS_ACCOUNT_ROLE_NAME", "CostDetectiveScanRole")
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
    kwargs: dict[str, str] = {"RoleArn": role_arn, "RoleSessionName": "cost-detective"}
    external_id = os.getenv("CROSS_ACCOUNT_EXTERNAL_ID")
    if external_id:
        kwargs["ExternalId"] = external_id

    try:
        resp = boto3.client("sts").assume_role(**kwargs)
    except (BotoCoreError, ClientError) as exc:
        raise AwsError(f"Could not assume {role_arn}: {exc}") from exc

    creds = resp["Credentials"]
    env = {
        "AWS_ACCESS_KEY_ID": creds["AccessKeyId"],
        "AWS_SECRET_ACCESS_KEY": creds["SecretAccessKey"],
        "AWS_SESSION_TOKEN": creds["SessionToken"],
    }
    _cred_cache[account_id] = {"env": env, "expiry": creds["Expiration"]}
    return env


# ─────────────────────────────────────────────────────────────────────────────
# Low-level CLI runner
# ─────────────────────────────────────────────────────────────────────────────
def _aws(args: list[str], region: str | None = None, timeout: int = 90) -> Any:
    """Run ``aws <args> --output json`` and return the parsed JSON.

    Raises :class:`AwsError` for the well-known failure modes and
    ``subprocess.CalledProcessError``-like wrapping for everything else.
    """
    if shutil.which("aws") is None:
        raise AwsError(
            "The AWS CLI (v2) was not found on PATH. Install it from "
            "https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
        )

    cmd = ["aws", *args, "--output", "json"]
    if region:
        cmd += ["--region", region]

    overrides = _aws_env.get()
    env = {**os.environ, **overrides} if overrides else None

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - env dependent
        raise AwsError(f"`{' '.join(cmd)}` timed out after {timeout}s") from exc

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        low = stderr.lower()
        if "unable to locate credentials" in low or "no credentials" in low:
            raise AwsError(
                "AWS credentials are not configured. Run `aws configure`, set "
                "AWS_PROFILE, or provide AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY."
            )
        if "could not connect to the endpoint url" in low or "invalid region" in low:
            raise AwsError(f"Invalid or unreachable AWS region. {stderr}")
        if "expiredtoken" in low or "the security token included in the request is expired" in low:
            raise AwsError("Your AWS session token has expired. Re-authenticate and retry.")
        if "opt-in" in low and "cost explorer" in low:
            raise AwsError(
                "Cost Explorer is not enabled for this account. Enable it in the AWS "
                "Billing console (Cost Explorer > Enable), then wait ~24h for data."
            )
        # AccessDenied is surfaced to the caller, which decides whether to continue.
        raise AwsError(stderr or f"`{' '.join(cmd)}` failed (exit {proc.returncode})")

    out = proc.stdout.strip()
    if not out:
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:  # pragma: no cover
        raise AwsError(f"Could not parse AWS CLI output as JSON: {exc}") from exc


def _safe(args: list[str], region: str | None, warnings: list[str], label: str) -> Any:
    """`_aws` wrapper that records the error and returns ``None`` instead of raising."""
    try:
        return _aws(args, region=region)
    except AwsError as exc:
        warnings.append(f"{label}: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Simple listings (used by GET endpoints)
# ─────────────────────────────────────────────────────────────────────────────
def list_regions() -> list[str]:
    data = _aws(
        ["ec2", "describe-regions", "--query", "Regions[].RegionName"]
    )
    regions = sorted(data or [])
    return regions or ["us-east-1", "us-east-2", "us-west-1", "us-west-2", "eu-west-1"]


def list_resource_groups() -> list[str]:
    try:
        data = _aws(["resource-groups", "list-groups"])
    except AwsError:
        # Resource Groups is optional scoping; never block the UI on it.
        return []
    groups = data.get("GroupIdentifiers") or data.get("Groups") or []
    names = []
    for g in groups:
        name = g.get("GroupName") or g.get("Name")
        if name:
            names.append(name)
    return sorted(names)


# ─────────────────────────────────────────────────────────────────────────────
# Inventory: Resource Groups Tagging API
# ─────────────────────────────────────────────────────────────────────────────
def _service_from_arn(arn: str) -> str:
    # arn:partition:service:region:account:resource
    parts = arn.split(":")
    return parts[2] if len(parts) > 2 else "unknown"


def _type_from_arn(arn: str) -> str:
    parts = arn.split(":", 5)
    tail = parts[5] if len(parts) > 5 else ""
    if "/" in tail:
        return tail.split("/")[0]
    if ":" in tail:
        return tail.split(":")[0]
    return tail or "resource"


def scan_inventory(region: str, resource_group: str | None, warnings: list[str]) -> list[dict]:
    args = ["resourcegroupstaggingapi", "get-resources"]
    if resource_group:
        # Treat the "resource group" as a tag filter: aws:resourcegroups:groupName
        args += [
            "--tag-filters",
            f"Key=aws:resourcegroups:groupName,Values={resource_group}",
        ]

    resources: list[dict] = []
    token: str | None = None
    for _ in range(50):  # hard page cap
        page_args = list(args)
        if token:
            page_args += ["--pagination-token", token]
        data = _safe(page_args, region, warnings, "resourcegroupstaggingapi:GetResources")
        if not data:
            break
        for item in data.get("ResourceTagMappingList", []):
            arn = item.get("ResourceARN", "")
            resources.append(
                {
                    "arn": arn,
                    "service": _service_from_arn(arn),
                    "type": _type_from_arn(arn),
                    "region": region,
                    "tags": {t["Key"]: t["Value"] for t in item.get("Tags", [])},
                }
            )
        token = data.get("PaginationToken") or ""
        if not token:
            break
    return resources


# ─────────────────────────────────────────────────────────────────────────────
# Cost Explorer
# ─────────────────────────────────────────────────────────────────────────────
def _month_start(d: date) -> date:
    return d.replace(day=1)


def scan_cost(warnings: list[str]) -> dict:
    today = datetime.now(timezone.utc).date()
    start = _month_start(today) - timedelta(days=1)
    start = _month_start(start)  # first day of previous month
    end = today + timedelta(days=1)  # End is exclusive

    data = _safe(
        [
            "ce",
            "get-cost-and-usage",
            "--time-period",
            f"Start={start.isoformat()},End={end.isoformat()}",
            "--granularity",
            "MONTHLY",
            "--metrics",
            "UnblendedCost",
            "--group-by",
            "Type=DIMENSION,Key=SERVICE",
        ],
        region="us-east-1",  # Cost Explorer is global, pinned to us-east-1
        warnings=warnings,
        label="ce:GetCostAndUsage",
    )
    if not data:
        return {"available": False}

    periods = data.get("ResultsByTime", [])
    currency = "USD"
    months = []
    for p in periods:
        by_service = []
        total = 0.0
        for g in p.get("Groups", []):
            amt = float(g["Metrics"]["UnblendedCost"]["Amount"])
            currency = g["Metrics"]["UnblendedCost"].get("Unit", currency)
            if amt > 0:
                by_service.append({"service": g["Keys"][0], "amount": round(amt, 2)})
        by_service.sort(key=lambda x: x["amount"], reverse=True)
        total = round(sum(s["amount"] for s in by_service), 2)
        months.append(
            {
                "start": p["TimePeriod"]["Start"],
                "end": p["TimePeriod"]["End"],
                "total": total,
                "by_service": by_service,
            }
        )

    latest = months[-1] if months else {"total": 0.0, "by_service": []}
    previous = months[-2] if len(months) >= 2 else None
    return {
        "available": True,
        "currency": currency,
        "current_month_to_date": latest["total"],
        "previous_month": previous["total"] if previous else None,
        "top_services": latest["by_service"][:10],
        "months": months,
    }


def scan_rightsizing(warnings: list[str]) -> dict:
    data = _safe(
        ["ce", "get-rightsizing-recommendation", "--service", "AmazonEC2"],
        region="us-east-1",
        warnings=warnings,
        label="ce:GetRightsizingRecommendation",
    )
    if not data:
        return {"available": False}
    summary = data.get("Summary", {})
    recs = []
    for r in data.get("RightsizingRecommendations", [])[:25]:
        cur = r.get("CurrentInstance", {})
        recs.append(
            {
                "instance_id": cur.get("ResourceId"),
                "current_type": (cur.get("InstanceType") or {}) or cur.get("ResourceDetails", {}).get(
                    "EC2ResourceDetails", {}
                ).get("InstanceType"),
                "recommended_action": r.get("RightsizingType"),
                "estimated_monthly_savings": r.get("ModifyRecommendationDetail", {})
                .get("TargetInstances", [{}])[0]
                .get("EstimatedMonthlySavings")
                or r.get("TerminateRecommendationDetail", {}).get("EstimatedMonthlySavings"),
            }
        )
    return {
        "available": True,
        "total_recommendations": summary.get("TotalRecommendationCount"),
        "estimated_total_monthly_savings": summary.get("EstimatedTotalMonthlySavingsAmount"),
        "recommendations": recs,
    }


def scan_savings_plans(warnings: list[str]) -> dict:
    data = _safe(
        [
            "ce",
            "get-savings-plans-purchase-recommendation",
            "--savings-plans-type",
            "COMPUTE_SP",
            "--term-in-years",
            "ONE_YEAR",
            "--payment-option",
            "NO_UPFRONT",
            "--lookback-period-in-days",
            "THIRTY_DAYS",
        ],
        region="us-east-1",
        warnings=warnings,
        label="ce:GetSavingsPlansPurchaseRecommendation",
    )
    if not data:
        return {"available": False}
    detail = data.get("SavingsPlansPurchaseRecommendation", {}).get(
        "SavingsPlansPurchaseRecommendationSummary", {}
    )
    return {
        "available": True,
        "estimated_monthly_savings": detail.get("EstimatedMonthlySavingsAmount"),
        "estimated_savings_percentage": detail.get("EstimatedSavingsPercentage"),
        "hourly_commitment_to_purchase": detail.get("HourlyCommitmentToPurchase"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Idle / misconfigured resource probes
# ─────────────────────────────────────────────────────────────────────────────
def scan_idle(region: str, warnings: list[str]) -> dict:
    idle: dict[str, list] = {}

    vols = _safe(
        ["ec2", "describe-volumes", "--filters", "Name=status,Values=available"],
        region, warnings, "ec2:DescribeVolumes(unattached)",
    )
    idle["unattached_ebs_volumes"] = [
        {
            "volume_id": v["VolumeId"],
            "size_gib": v["Size"],
            "type": v["VolumeType"],
            "created": v.get("CreateTime"),
        }
        for v in (vols or {}).get("Volumes", [])
    ]

    gp2 = _safe(
        ["ec2", "describe-volumes", "--filters", "Name=volume-type,Values=gp2"],
        region, warnings, "ec2:DescribeVolumes(gp2)",
    )
    idle["gp2_volumes"] = [
        {"volume_id": v["VolumeId"], "size_gib": v["Size"]}
        for v in (gp2 or {}).get("Volumes", [])
    ]

    addrs = _safe(["ec2", "describe-addresses"], region, warnings, "ec2:DescribeAddresses")
    idle["unassociated_elastic_ips"] = [
        {"public_ip": a["PublicIp"], "allocation_id": a.get("AllocationId")}
        for a in (addrs or {}).get("Addresses", [])
        if not a.get("AssociationId") and not a.get("InstanceId")
    ]

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    snaps = _safe(
        ["ec2", "describe-snapshots", "--owner-ids", "self"],
        region, warnings, "ec2:DescribeSnapshots",
    )
    old_snaps = []
    for s in (snaps or {}).get("Snapshots", []):
        started = s.get("StartTime", "")
        try:
            when = datetime.fromisoformat(started.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when < cutoff:
            old_snaps.append(
                {"snapshot_id": s["SnapshotId"], "volume_size_gib": s.get("VolumeSize"), "started": started}
            )
    idle["snapshots_older_than_90d"] = old_snaps

    albs = _safe(["elbv2", "describe-load-balancers"], region, warnings, "elbv2:DescribeLoadBalancers")
    tgs = _safe(["elbv2", "describe-target-groups"], region, warnings, "elbv2:DescribeTargetGroups")
    tg_by_lb: dict[str, int] = {}
    for tg in (tgs or {}).get("TargetGroups", []):
        for lb_arn in tg.get("LoadBalancerArns", []):
            tg_by_lb[lb_arn] = tg_by_lb.get(lb_arn, 0) + 1
    idle["load_balancers_without_target_groups"] = [
        {"name": lb["LoadBalancerName"], "type": lb["Type"], "arn": lb["LoadBalancerArn"]}
        for lb in (albs or {}).get("LoadBalancers", [])
        if tg_by_lb.get(lb["LoadBalancerArn"], 0) == 0
    ]

    classic = _safe(["elb", "describe-load-balancers"], region, warnings, "elb:DescribeLoadBalancers")
    idle["classic_load_balancers_without_instances"] = [
        {"name": lb["LoadBalancerName"]}
        for lb in (classic or {}).get("LoadBalancerDescriptions", [])
        if not lb.get("Instances")
    ]

    nats = _safe(["ec2", "describe-nat-gateways"], region, warnings, "ec2:DescribeNatGateways")
    idle["nat_gateways"] = [
        {"nat_gateway_id": n["NatGatewayId"], "state": n["State"], "vpc_id": n.get("VpcId")}
        for n in (nats or {}).get("NatGateways", [])
        if n.get("State") == "available"
    ]

    logs = _safe(["logs", "describe-log-groups"], region, warnings, "logs:DescribeLogGroups")
    idle["log_groups_without_retention"] = [
        {
            "name": lg["logGroupName"],
            "stored_bytes": lg.get("storedBytes", 0),
        }
        for lg in (logs or {}).get("logGroups", [])
        if not lg.get("retentionInDays")
    ]

    return idle


def scan_databases(region: str, warnings: list[str]) -> list[dict]:
    data = _safe(["rds", "describe-db-instances"], region, warnings, "rds:DescribeDBInstances")
    out = []
    for db in (data or {}).get("DBInstances", []):
        out.append(
            {
                "identifier": db["DBInstanceIdentifier"],
                "engine": db["Engine"],
                "instance_class": db["DBInstanceClass"],
                "allocated_storage_gib": db.get("AllocatedStorage"),
                "multi_az": db.get("MultiAZ"),
                "storage_type": db.get("StorageType"),
            }
        )
    return out


def scan_instances(region: str, warnings: list[str]) -> list[dict]:
    data = _safe(["ec2", "describe-instances"], region, warnings, "ec2:DescribeInstances")
    out = []
    for res in (data or {}).get("Reservations", []):
        for i in res.get("Instances", []):
            if i.get("State", {}).get("Name") == "terminated":
                continue
            out.append(
                {
                    "instance_id": i["InstanceId"],
                    "type": i["InstanceType"],
                    "state": i["State"]["Name"],
                    "lifecycle": i.get("InstanceLifecycle", "on-demand"),
                    "launch_time": i.get("LaunchTime"),
                }
            )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────
def scan_region(
    region: str,
    resource_group: str | None = None,
    progress: ProgressCb = None,
    account_id: str | None = None,
) -> dict:
    """Full scan for one region. Returns the payload handed to the AI analyzer.

    If ``account_id`` is given, every AWS CLI call runs with credentials assumed
    into that account for the duration of this call.
    """

    def emit(stage: str, message: str, pct: int) -> None:
        if progress:
            progress(stage, message, pct)

    token = None
    if account_id:
        emit("scan", f"Assuming role in account {account_id}...", 12)
        token = _aws_env.set(_assume_role_env(account_id))

    try:
        warnings: list[str] = []

        emit("scan", f"Scanning resources in {region}...", 20)
        inventory = scan_inventory(region, resource_group, warnings)
        instances = scan_instances(region, warnings)
        databases = scan_databases(region, warnings)

        emit("idle", f"Checking for idle resources in {region}...", 35)
        idle = scan_idle(region, warnings)

        emit("cost", "Fetching spend from Cost Explorer...", 50)
        cost = scan_cost(warnings)
        rightsizing = scan_rightsizing(warnings)
        savings_plans = scan_savings_plans(warnings)

        return {
            "region": region,
            "resource_group": resource_group,
            "account_id": account_id or None,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "resource_count": len(inventory),
            "resources": inventory,
            "ec2_instances": instances,
            "rds_instances": databases,
            "idle": idle,
            "cost": cost,
            "rightsizing": rightsizing,
            "savings_plans_recommendation": savings_plans,
            "warnings": warnings,
        }
    finally:
        if token is not None:
            _aws_env.reset(token)
