"""OpenAI-powered cost analysis (see prompts/02-openai-analysis.md).

Takes the scan payload from :mod:`aws_scanner` and asks ``gpt-4o`` to turn it
into a structured report: a summary, a list of issues with severity, an
estimated monthly saving, and a runnable AWS CLI fix command per issue.
"""
from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI

_SYSTEM = """You are a senior AWS cost-optimization engineer.
You are given a JSON snapshot of one AWS region: the resource inventory, EC2 and
RDS instances, idle-resource probes, AWS Cost Explorer spend, Cost Explorer
rightsizing recommendations, and a Savings Plans purchase recommendation.

Analyse it for:
  - over-provisioning (EC2 / RDS / Fargate larger than needed)
  - unused / idle resources (unattached EBS, unassociated Elastic IPs, idle
    ALB/NLB/CLB, idle NAT gateways, stale snapshots)
  - misconfiguration (on-demand that should be Savings Plans / Reserved
    Instances, gp2 volumes that should be gp3, CloudWatch log groups with no
    retention, S3 without lifecycle)
  - wrong storage classes / pricing tiers and other cost opportunities

Ground your savings estimates in the Cost Explorer numbers when they are
present. Every issue MUST include a concrete, copy-pasteable AWS CLI v2 command
that remediates it (a `aws ...` command). Never invent resource IDs — only use
IDs that appear in the input. If nothing is wrong, return an empty issues list.

Respond with ONLY a JSON object of this exact shape:
{
  "summary": "2-4 sentence overview",
  "estimated_monthly_savings": "$<number> (approx)",
  "issues": [
    {
      "resource": "<name or ARN or ID>",
      "issue_type": "over-provisioned" | "unused" | "misconfigured",
      "severity": "high" | "medium" | "low",
      "explanation": "why this costs money and what to do",
      "fix_command": "aws ..."
    }
  ]
}
"""

# Keep the prompt within a sane token budget.
_MAX_RESOURCES = 120


class AnalyzerError(RuntimeError):
    pass


def _trim(scan: dict[str, Any]) -> dict[str, Any]:
    slim = dict(scan)
    resources = slim.get("resources", [])
    if len(resources) > _MAX_RESOURCES:
        slim["resources"] = resources[:_MAX_RESOURCES]
        slim["resources_truncated"] = len(resources) - _MAX_RESOURCES
    return slim


def _client() -> OpenAI:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise AnalyzerError(
            "OPENAI_API_KEY is not set. Copy backend/.env.example to backend/.env "
            "and fill it in."
        )
    return OpenAI(api_key=key)


def analyze(scan: dict[str, Any]) -> dict[str, Any]:
    """Blocking call — run it via ``asyncio.to_thread`` from async code."""
    client = _client()
    model = os.getenv("OPENAI_MODEL", "gpt-4o")

    user_payload = json.dumps(_trim(scan), default=str)

    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user_payload},
            ],
        )
    except Exception as exc:  # noqa: BLE001 - surface the provider error verbatim
        raise AnalyzerError(f"OpenAI request failed: {exc}") from exc

    raw = resp.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AnalyzerError(f"Model did not return valid JSON: {exc}") from exc

    issues = parsed.get("issues") or []
    normalised = []
    for it in issues:
        normalised.append(
            {
                "resource": it.get("resource", "unknown"),
                "issue_type": it.get("issue_type", "misconfigured"),
                "severity": (it.get("severity") or "low").lower(),
                "explanation": it.get("explanation", ""),
                "fix_command": it.get("fix_command", ""),
            }
        )

    return {
        "summary": parsed.get("summary", ""),
        "estimated_monthly_savings": parsed.get("estimated_monthly_savings", "$0"),
        "issues": normalised,
        "model": model,
    }
