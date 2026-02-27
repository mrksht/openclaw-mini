"""GitLab Merge Request tool — fetch MR details from GitLab API.

Requires GITLAB_URL and GITLAB_PRIVATE_TOKEN env vars.
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

# Matches GitLab MR URLs like:
#   https://gitlab.com/group/project/-/merge_requests/123
#   https://gitlab.example.com/team/repo/-/merge_requests/42
GITLAB_MR_PATTERN = re.compile(
    r"https?://[^/\s]+/(.+?)/-/merge_requests/(\d+)"
)


def _gitlab_api_get(base_url: str, token: str, endpoint: str) -> dict[str, Any] | None:
    """Make a GET request to the GitLab API."""
    url = f"{base_url.rstrip('/')}/api/v4{endpoint}"
    req = urllib.request.Request(
        url,
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


def _format_mr_info(mr: dict[str, Any]) -> str:
    """Format a GitLab MR API response into a human-readable summary."""
    title = mr.get("title", "Unknown")
    state = mr.get("state", "unknown")
    author = mr.get("author", {}).get("name", "Unknown")
    web_url = mr.get("web_url", "")
    source_branch = mr.get("source_branch", "")
    target_branch = mr.get("target_branch", "")
    created_at = mr.get("created_at", "")[:10]  # date only
    updated_at = mr.get("updated_at", "")[:10]

    reviewers = mr.get("reviewers", [])
    reviewer_names = ", ".join(r.get("name", "?") for r in reviewers) if reviewers else "None assigned"

    approvals_info = ""
    if mr.get("approved", False):
        approvals_info = " ✅ Approved"

    lines = [
        f"**{title}**",
        f"  State: {state}{approvals_info}",
        f"  Author: {author}",
        f"  Branch: {source_branch} → {target_branch}",
        f"  Reviewers: {reviewer_names}",
        f"  Created: {created_at} | Updated: {updated_at}",
        f"  URL: {web_url}",
    ]
    return "\n".join(lines)


def extract_mr_links(text: str) -> list[tuple[str, str]]:
    """Extract GitLab MR links from text.

    Returns list of (project_path, mr_iid) tuples.
    """
    return GITLAB_MR_PATTERN.findall(text)


def create_gitlab_mr_tool(gitlab_url: str, private_token: str) -> Tool:
    """Create the gitlab_mr tool for fetching MR details.

    Args:
        gitlab_url: Base GitLab URL (e.g., https://gitlab.com).
        private_token: GitLab personal access token.
    """

    def fetch_mr(tool_input: dict[str, Any]) -> str:
        mr_url = tool_input.get("mr_url", "")

        if not private_token:
            return "Error: GITLAB_PRIVATE_TOKEN not configured."

        # Parse the MR URL
        match = GITLAB_MR_PATTERN.search(mr_url)
        if not match:
            return f"Error: Could not parse GitLab MR URL: {mr_url}"

        project_path = match.group(1)
        mr_iid = match.group(2)

        # URL-encode the project path (slashes → %2F)
        encoded_path = urllib.request.quote(project_path, safe="")

        # Fetch MR details
        mr_data = _gitlab_api_get(
            gitlab_url, private_token,
            f"/projects/{encoded_path}/merge_requests/{mr_iid}",
        )
        if not mr_data:
            return f"Error: Could not fetch MR {mr_url} — check permissions or URL."

        return _format_mr_info(mr_data)

    return Tool(
        name="gitlab_mr",
        description=(
            "Fetch details about a GitLab Merge Request given its URL. "
            "Returns title, state, author, reviewers, and approval status."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "mr_url": {
                    "type": "string",
                    "description": (
                        "Full GitLab MR URL, e.g. "
                        "https://gitlab.com/group/project/-/merge_requests/123"
                    ),
                },
            },
            "required": ["mr_url"],
        },
        handler=fetch_mr,
    )
