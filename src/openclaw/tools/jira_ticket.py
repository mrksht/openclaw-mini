"""Jira ticket tool — search, view, comment, and transition issues.

Requires environment variables:
  JIRA_URL          — e.g. https://yourcompany.atlassian.net
  JIRA_USER_EMAIL   — your Atlassian account email
  JIRA_API_TOKEN    — API token from https://id.atlassian.com/manage-profile/security/api-tokens
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.request
import urllib.error
from typing import Any

from openclaw.tools.registry import Tool

logger = logging.getLogger(__name__)


def _jira_request(
    base_url: str,
    email: str,
    token: str,
    endpoint: str,
    method: str = "GET",
    payload: dict | None = None,
) -> dict[str, Any] | None:
    """Make an authenticated request to the Jira REST API v3."""
    url = f"{base_url.rstrip('/')}/rest/api/3{endpoint}"
    creds = base64.b64encode(f"{email}:{token}".encode()).decode()
    data = json.dumps(payload).encode("utf-8") if payload else None

    req = urllib.request.Request(
        url,
        method=method,
        data=data,
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body.strip() else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        logger.warning("Jira API %s %s: %s — %s", method, endpoint, e.code, body)
        return None
    except Exception as e:
        logger.warning("Jira request failed: %s", e)
        return None


_STATUS_EMOJI = {
    "to do": "📋",
    "in progress": "🔄",
    "in review": "👀",
    "done": "✅",
    "closed": "✅",
    "blocked": "🚫",
}


def _extract_adf_text(node: dict | list) -> str:
    """Recursively extract plain text from Atlassian Document Format."""
    if isinstance(node, list):
        return " ".join(_extract_adf_text(n) for n in node)
    if not isinstance(node, dict):
        return str(node)
    if node.get("type") == "text":
        return node.get("text", "")
    content = node.get("content", [])
    parts = [_extract_adf_text(c) for c in content]
    return " ".join(p for p in parts if p)


def _format_issue(issue: dict[str, Any], base_url: str) -> str:
    """Format a Jira issue into a readable summary."""
    key = issue.get("key", "?")
    fields = issue.get("fields", {})
    summary = fields.get("summary", "(no summary)")
    status = fields.get("status", {}).get("name", "?")
    emoji = _STATUS_EMOJI.get(status.lower(), "📌")
    priority = (
        fields.get("priority", {}).get("name", "None")
        if fields.get("priority")
        else "None"
    )
    assignee = (
        fields.get("assignee", {}).get("displayName", "Unassigned")
        if fields.get("assignee")
        else "Unassigned"
    )
    reporter = (
        fields.get("reporter", {}).get("displayName", "?")
        if fields.get("reporter")
        else "?"
    )
    issue_type = (
        fields.get("issuetype", {}).get("name", "?")
        if fields.get("issuetype")
        else "?"
    )
    created = (fields.get("created") or "")[:10]
    updated = (fields.get("updated") or "")[:10]
    labels = ", ".join(fields.get("labels", [])) or "None"
    url = f"{base_url.rstrip('/')}/browse/{key}"

    # Extract description text (Jira uses ADF format)
    desc_field = fields.get("description")
    description = ""
    if desc_field and isinstance(desc_field, dict):
        description = _extract_adf_text(desc_field)
    elif isinstance(desc_field, str):
        description = desc_field

    if len(description) > 300:
        description = description[:300].rsplit(" ", 1)[0] + "…"

    lines = [
        f"{emoji} **{key}: {summary}**",
        f"  Type: {issue_type} | Priority: {priority}",
        f"  Status: {status}",
        f"  Assignee: {assignee} | Reporter: {reporter}",
        f"  Labels: {labels}",
        f"  Created: {created} | Updated: {updated}",
        f"  URL: {url}",
    ]
    if description:
        lines.append(f"  Description: {description}")
    return "\n".join(lines)


def _format_issue_short(issue: dict[str, Any]) -> str:
    """Format a Jira issue as a compact one-liner for search results."""
    key = issue.get("key", "?")
    fields = issue.get("fields", {})
    summary = fields.get("summary", "")
    status = fields.get("status", {}).get("name", "?")
    emoji = _STATUS_EMOJI.get(status.lower(), "📌")
    assignee = (
        fields.get("assignee", {}).get("displayName", "Unassigned")
        if fields.get("assignee")
        else "Unassigned"
    )
    priority = (
        fields.get("priority", {}).get("name", "")
        if fields.get("priority")
        else ""
    )
    prio_str = f" [{priority}]" if priority else ""

    return (
        f"{emoji} **{key}**: {summary}{prio_str}\n"
        f"   Status: {status} | Assignee: {assignee}"
    )


def create_jira_tool(jira_url: str, user_email: str, api_token: str) -> Tool:
    """Create the jira_ticket tool.

    Args:
        jira_url: Jira instance URL (e.g. https://yourco.atlassian.net).
        user_email: Atlassian account email for authentication.
        api_token: Jira API token.
    """

    def jira_ticket(tool_input: dict[str, Any]) -> str:
        action = tool_input.get("action", "get")

        if not api_token:
            return "Error: JIRA_API_TOKEN not configured."

        # ── get: fetch a single issue by key ──
        if action == "get":
            issue_key = tool_input.get("issue_key", "")
            if not issue_key:
                return "Error: 'issue_key' is required (e.g. 'PROJ-123')."

            issue = _jira_request(
                jira_url, user_email, api_token,
                f"/issue/{issue_key}",
            )
            if not issue:
                return f"Error: Could not fetch {issue_key}. Check the key and permissions."
            return _format_issue(issue, jira_url)

        # ── search: JQL search ──
        elif action == "search":
            jql = tool_input.get("jql", "")
            if not jql:
                jql = (
                    "assignee = currentUser() AND status != Done "
                    "ORDER BY updated DESC"
                )

            encoded_jql = urllib.request.quote(jql, safe="")
            result = _jira_request(
                jira_url, user_email, api_token,
                f"/search/jql?jql={encoded_jql}&maxResults=25"
                "&fields=key,summary,status,assignee,priority,issuetype,updated",
            )
            if not result:
                return "Error: Jira search failed. Check your JQL syntax and permissions."

            issues = result.get("issues", [])
            total = result.get("total", 0)
            if not issues:
                return f"No issues found for: {jql}"

            lines = [f"**Jira search** ({len(issues)} of {total} results):\n"]
            for issue in issues:
                lines.append(_format_issue_short(issue))
            return "\n".join(lines)

        # ── comment: add a comment to an issue ──
        elif action == "comment":
            issue_key = tool_input.get("issue_key", "")
            comment_body = tool_input.get("comment", "")
            if not issue_key or not comment_body:
                return "Error: 'issue_key' and 'comment' are required."

            # Jira v3 requires Atlassian Document Format for comment body
            adf_body = {
                "body": {
                    "version": 1,
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": comment_body}
                            ],
                        }
                    ],
                }
            }
            result = _jira_request(
                jira_url, user_email, api_token,
                f"/issue/{issue_key}/comment",
                method="POST",
                payload=adf_body,
            )
            if result is not None:
                return f"✅ Comment added to {issue_key}."
            return f"Error: Could not add comment to {issue_key}."

        # ── transition: move issue to a new status ──
        elif action == "transition":
            issue_key = tool_input.get("issue_key", "")
            target_status = tool_input.get("status", "")
            if not issue_key or not target_status:
                return "Error: 'issue_key' and 'status' are required."

            # Get available transitions for this issue
            transitions = _jira_request(
                jira_url, user_email, api_token,
                f"/issue/{issue_key}/transitions",
            )
            if not transitions:
                return f"Error: Could not fetch transitions for {issue_key}."

            available = transitions.get("transitions", [])
            target_lower = target_status.lower()
            matched = None
            for t in available:
                if t.get("name", "").lower() == target_lower:
                    matched = t
                    break

            if not matched:
                names = ", ".join(f"'{t['name']}'" for t in available)
                return (
                    f"Status '{target_status}' not available for {issue_key}. "
                    f"Available transitions: {names}"
                )

            result = _jira_request(
                jira_url, user_email, api_token,
                f"/issue/{issue_key}/transitions",
                method="POST",
                payload={"transition": {"id": matched["id"]}},
            )
            if result is not None:
                return f"✅ {issue_key} moved to '{matched['name']}'."
            return f"Error: Could not transition {issue_key}."

        # ── my_issues: shortcut for assigned open issues ──
        elif action == "my_issues":
            jql = (
                "assignee = currentUser() AND status != Done "
                "ORDER BY priority DESC, updated DESC"
            )
            return jira_ticket({"action": "search", "jql": jql})

        else:
            return (
                f"Unknown action '{action}'. "
                "Use 'get', 'search', 'comment', 'transition', or 'my_issues'."
            )

    return Tool(
        name="jira_ticket",
        description=(
            "Interact with Jira: look up tickets, search with JQL, add comments, "
            "or transition issues to a new status. Use 'my_issues' to see your open work."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "search", "comment", "transition", "my_issues"],
                    "description": (
                        "'get' = fetch single issue, 'search' = JQL search, "
                        "'comment' = add comment, 'transition' = change status, "
                        "'my_issues' = your open assigned tickets"
                    ),
                },
                "issue_key": {
                    "type": "string",
                    "description": "Jira issue key, e.g. 'PROJ-123' (for get/comment/transition)",
                },
                "jql": {
                    "type": "string",
                    "description": "JQL query string for search (e.g. 'project = PROJ AND status = Open')",
                },
                "comment": {
                    "type": "string",
                    "description": "Comment text to add (for comment action)",
                },
                "status": {
                    "type": "string",
                    "description": "Target status name, e.g. 'In Progress' (for transition action)",
                },
            },
            "required": ["action"],
        },
        handler=jira_ticket,
    )
