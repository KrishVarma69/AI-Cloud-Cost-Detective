"""LLM-powered cost analysis (see prompts/02-openai-analysis.md).

Takes the scan payload from :mod:`aws_scanner` and asks an LLM to turn it into a
structured report: a summary, a list of issues with severity, an estimated
monthly saving, and a runnable AWS CLI fix command per issue.

Two providers, selected with the ``LLM_PROVIDER`` env var:

* ``openai``  (default) — OpenAI Chat Completions. Needs ``OPENAI_API_KEY``.
  The scan payload (ARNs, account ids, tag values) leaves your network.
* ``bedrock`` — Amazon Bedrock (Anthropic Claude) via the boto3 Converse API.
  Data stays inside your AWS account/region. Uses the same AWS credential chain
  as the scanner; requires model access enabled in the Bedrock console.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

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


# ── provider: OpenAI ─────────────────────────────────────────────────────────
def _complete_openai(system: str, user_payload: str) -> tuple[str, str]:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise AnalyzerError(
            "LLM_PROVIDER=openai but the 'openai' package is not installed."
        ) from exc

    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise AnalyzerError(
            "OPENAI_API_KEY is not set. Copy backend/.env.example to backend/.env "
            "and fill it in, or switch LLM_PROVIDER to 'bedrock'."
        )
    model = os.getenv("OPENAI_MODEL", "gpt-4o")
    client = OpenAI(api_key=key)
    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_payload},
            ],
        )
    except Exception as exc:  # noqa: BLE001 - surface the provider error verbatim
        raise AnalyzerError(f"OpenAI request failed: {exc}") from exc

    return resp.choices[0].message.content or "{}", model


# ── provider: Amazon Bedrock ─────────────────────────────────────────────────
def _complete_bedrock(system: str, user_payload: str) -> tuple[str, str]:
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError as exc:  # pragma: no cover
        raise AnalyzerError(
            "LLM_PROVIDER=bedrock but 'boto3' is not installed. "
            "Add it to backend/requirements.txt."
        ) from exc

    model_id = os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
    region = os.getenv("BEDROCK_REGION") or os.getenv("AWS_REGION") or "us-east-1"
    client = boto3.client("bedrock-runtime", region_name=region)

    try:
        resp = client.converse(
            modelId=model_id,
            system=[{"text": system}],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "text": user_payload
                            + "\n\nReturn ONLY the JSON object — no prose, no markdown fences."
                        }
                    ],
                }
            ],
            inferenceConfig={"temperature": 0.2, "maxTokens": 4096},
        )
    except (BotoCoreError, ClientError) as exc:
        raise AnalyzerError(f"Bedrock request failed: {exc}") from exc

    try:
        text = resp["output"]["message"]["content"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise AnalyzerError(f"Unexpected Bedrock response shape: {exc}") from exc

    return text, model_id


# ── shared: response parsing ─────────────────────────────────────────────────
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(raw: str) -> dict[str, Any]:
    """Best-effort: strip markdown fences / stray prose, then json.loads."""
    text = (raw or "").strip()
    fence = _JSON_FENCE.search(text)
    if fence:
        text = fence.group(1).strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AnalyzerError(f"Model did not return valid JSON: {exc}") from exc


def analyze(scan: dict[str, Any]) -> dict[str, Any]:
    """Blocking call — run it via ``asyncio.to_thread`` from async code."""
    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    user_payload = json.dumps(_trim(scan), default=str)

    if provider == "bedrock":
        raw, model = _complete_bedrock(_SYSTEM, user_payload)
    elif provider == "openai":
        raw, model = _complete_openai(_SYSTEM, user_payload)
    else:
        raise AnalyzerError(
            f"Unknown LLM_PROVIDER '{provider}'. Use 'openai' or 'bedrock'."
        )

    parsed = _extract_json(raw)

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
        "provider": provider,
    }
