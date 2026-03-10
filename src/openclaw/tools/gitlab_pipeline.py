"""GitLab Pipeline tool — check CI/CD status and retrigger jobs.

Requires GITLAB_URL and GITLAB_PRIVATE_TOKEN env vars (same as gitlab_mr).

Capabilities:
  - Check pipeline status for a branch or MR
  - List recent pipelines for a project
  - Retrigger a failed pipeline
  - Get details of failed jobs
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
import urllib.error
from typing import Any

from openclaw.tools.registry import Tool

logger = logging.getLogger(__name__)

GITLAB_MR_PATTERN = re.compile(
    r"https?://[^/\s]+/(.+?)/-/merge_requests/(\d+)"
)

_STATUS_EMOJI = {
    "success": "✅",
    "failed": "❌",
    "running": "🔄",
    "pending": "⏳",
    "canceled": "🚫",
    "skipped": "⏭️",
    "manual": "👆",
    "created": "🆕",
    "waiting_for_resource": "⏳",
}


def _api_request(
    base_url: str,
    token: str,
    endpoint: str,
    method: str = "GET",
    data: bytes | None = None,
) -> dict[str, Any] | list | None:
    """Make an authenticated request to the GitLab API."""
    url = f"{base_url.rstrip('/')}/api/v4{endpoint}"
    req = urllib.request.Request(
        url,
        method=method,
        data=data,
        headers={
            "PRIVATE-TOKEN": token,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        logger.warning("GitLab API error %s: %s", e.code, e.reason)
        return None
    except Exception as e:
        logger.warning("GitLab API request failed: %s", e)
        return None


def _format_pipeline(pipeline: dict[str, Any]) -> str:
    """Format a pipeline dict into a readable summary."""
    status = pipeline.get("status", "unknown")
    emoji = _STATUS_EMOJI.get(status, "❓")
    pid = pipeline.get("id", "?")
    ref = pipeline.get("ref", "?")
    source = pipeline.get("source", "")
    created = pipeline.get("created_at", "")[:16].replace("T", " ")
    web_url = pipeline.get("web_url", "")

    line = f"{emoji} Pipeline #{pid} [{status}] on `{ref}`"
    if source:
        line += f" ({source})"
    if created:
        line += f" — {created}"
    if web_url:
        line += f"\n   {web_url}"
    return line


def _format_job(job: dict[str, Any]) -> str:
    """Format a job dict into a readable line."""
    status = job.get("status", "unknown")
    emoji = _STATUS_EMOJI.get(status, "❓")
    name = job.get("name", "?")
    stage = job.get("stage", "?")
    duration = job.get("duration")
    duration_str = f" ({duration:.0f}s)" if duration else ""
    failure_reason = job.get("failure_reason", "")
    failure_str = f" — reason: {failure_reason}" if failure_reason else ""
    web_url = job.get("web_url", "")

    line = f"  {emoji} {stage}/{name}{duration_str}{failure_str}"
    if web_url:
        line += f"\n     {web_url}"
    return line


def create_gitlab_pipeline_tool(gitlab_url: str, private_token: str) -> Tool:
    """Create the gitlab_pipeline tool.

    Args:
        gitlab_url: Base GitLab URL (e.g. https://gitlab.com).
        private_token: GitLab personal access token.
    """

    def _encode_project(project_path: str) -> str:
        return urllib.request.quote(project_path, safe="")

    def _resolve_input(tool_input: dict[str, Any]) -> tuple[str, str | None, str | None]:
        """Return (encoded_project, branch_or_None, mr_iid_or_None)."""
        mr_url = tool_input.get("mr_url", "")
        if mr_url:
            match = GITLAB_MR_PATTERN.search(mr_url)
            if match:
                return _encode_project(match.group(1)), None, match.group(2)

        project = tool_input.get("project", "")
        branch = tool_input.get("branch", "")
        if project:
            return _encode_project(project), branch or None, None

        return "", None, None

    def _get_pipelines(
        encoded_project: str, branch: str | None, mr_iid: str | None,
        per_page: int = 5,
    ) -> list | None:
        """Fetch pipelines for a branch or MR."""
        if mr_iid:
            return _api_request(
                gitlab_url, private_token,
                f"/projects/{encoded_project}/merge_requests/{mr_iid}/pipelines",
            )
        params = f"?per_page={per_page}&sort=desc&order_by=id"
        if branch:
            params += f"&ref={urllib.request.quote(branch, safe='')}"
        return _api_request(
            gitlab_url, private_token,
            f"/projects/{encoded_project}/pipelines{params}",
        )

    def gitlab_pipeline(tool_input: dict[str, Any]) -> str:
        action = tool_input.get("action", "status")

        if not private_token:
            return "Error: GITLAB_PRIVATE_TOKEN not configured."

        encoded_project, branch, mr_iid = _resolve_input(tool_input)
        if not encoded_project:
            return (
                "Error: Provide either 'mr_url' (GitLab MR URL) or "
                "'project' (e.g. 'group/repo') to identify the project."
            )

        # ── status: show recent pipelines ──
        if action == "status":
            pipelines = _get_pipelines(encoded_project, branch, mr_iid)
            if not pipelines:
                ref_str = f" for MR !{mr_iid}" if mr_iid else (f" on `{branch}`" if branch else "")
                return f"No pipelines found{ref_str}."

            ref_str = f" for MR !{mr_iid}" if mr_iid else (f" on `{branch}`" if branch else "")
            count = min(5, len(pipelines))
            lines = [f"**Pipelines{ref_str}** (latest {count}):\n"]
            for p in pipelines[:5]:
                lines.append(_format_pipeline(p))
            return "\n".join(lines)

        # ── jobs: list jobs of a pipeline ──
        elif action == "jobs":
            pipeline_id = tool_input.get("pipeline_id")
            if not pipeline_id:
                pipelines = _get_pipelines(encoded_project, branch, mr_iid, per_page=1)
                if not pipelines:
                    return "No pipelines found to show jobs for."
                pipeline_id = pipelines[0]["id"]

            jobs = _api_request(
                gitlab_url, private_token,
                f"/projects/{encoded_project}/pipelines/{pipeline_id}/jobs?per_page=50",
            )
            if not jobs:
                return f"No jobs found for pipeline #{pipeline_id}."

            lines = [f"**Jobs for pipeline #{pipeline_id}:**\n"]
            for job in jobs:
                lines.append(_format_job(job))

            failed = [j for j in jobs if j.get("status") == "failed"]
            if failed:
                lines.append(f"\n⚠️ {len(failed)} failed job(s)")
            return "\n".join(lines)

        # ── retry: retrigger a failed pipeline ──
        elif action == "retry":
            pipeline_id = tool_input.get("pipeline_id")
            if not pipeline_id:
                pipelines = _get_pipelines(encoded_project, branch, mr_iid)
                if not pipelines:
                    return "No pipelines found to retry."
                for p in pipelines:
                    if p.get("status") == "failed":
                        pipeline_id = p["id"]
                        break
                if not pipeline_id:
                    return "No failed pipeline found to retry."

            result = _api_request(
                gitlab_url, private_token,
                f"/projects/{encoded_project}/pipelines/{pipeline_id}/retry",
                method="POST",
            )
            if result:
                return f"🔄 Retried pipeline #{pipeline_id}. New status: {result.get('status', '?')}"
            return f"Error: Could not retry pipeline #{pipeline_id}. Check permissions."

        else:
            return f"Unknown action '{action}'. Use 'status', 'jobs', or 'retry'."

    return Tool(
        name="gitlab_pipeline",
        description=(
            "Check GitLab CI/CD pipeline status, view job details, or retry failed pipelines. "
            "Provide either an MR URL or a project path (group/repo) with optional branch."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "jobs", "retry"],
                    "description": (
                        "What to do: 'status' = show recent pipelines, "
                        "'jobs' = list jobs in a pipeline, "
                        "'retry' = retrigger a failed pipeline"
                    ),
                },
                "mr_url": {
                    "type": "string",
                    "description": "GitLab MR URL — used to find the project and its pipelines",
                },
                "project": {
                    "type": "string",
                    "description": "GitLab project path, e.g. 'my-group/my-repo'",
                },
                "branch": {
                    "type": "string",
                    "description": "Branch name to filter pipelines (optional)",
                },
                "pipeline_id": {
                    "type": "integer",
                    "description": "Specific pipeline ID for 'jobs' or 'retry' (optional — defaults to latest)",
                },
            },
            "required": ["action"],
        },
        handler=gitlab_pipeline,
    )
