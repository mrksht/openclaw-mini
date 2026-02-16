"""Multi-agent router — prefix-based routing to different agent configurations.

Each agent has its own name, model, SOUL, and session prefix.
All agents share the same memory store and tool registry.
Messages are routed by prefix commands (e.g. `/research <query>`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from openclaw.agent.loop import OnToolUseCallback, run_agent_turn
from openclaw.agent.soul import build_system_prompt, load_soul
from openclaw.session.store import SessionStore
from openclaw.tools.registry import ToolRegistry


@dataclass
class AgentConfig:
    """Configuration for a single agent.

    Attributes:
        name: Human-readable agent name (e.g. "Jarvis", "Scout").
        model: LLM model identifier.
        soul_path: Path to the agent's SOUL.md file (None → built-in default).
        prefix: Command prefix that routes to this agent (e.g. "/research").
            The default agent has prefix = None.
        session_prefix: Used to build session keys (e.g. "agent:research").
        workspace_path: Workspace path injected into system prompt.
    """

    name: str
    model: str
    soul_path: str | None = None
    prefix: str | None = None
    session_prefix: str = "agent:main"
    workspace_path: str | None = None

    def __post_init__(self):
        self._soul: str | None = None
        self._system_prompt: str | None = None

    @property
    def soul(self) -> str:
        if self._soul is None:
            self._soul = load_soul(self.soul_path)
        return self._soul

    @property
    def system_prompt(self) -> str:
        if self._system_prompt is None:
            self._system_prompt = build_system_prompt(
                self.soul, workspace_path=self.workspace_path
            )
        return self._system_prompt


class AgentRouter:
    """Routes messages to the appropriate agent based on prefix commands.

    Usage::

        router = AgentRouter(
            default_agent=AgentConfig(name="Jarvis", model="claude-sonnet-4-5", ...),
            agents=[
                AgentConfig(name="Scout", model="claude-sonnet-4-5",
                           prefix="/research", session_prefix="agent:research", ...),
            ],
        )

        # Route and execute
        agent, user_text = router.resolve("/research quantum computing")
        # agent = Scout config, user_text = "quantum computing"
    """

    def __init__(
        self,
        default_agent: AgentConfig,
        agents: list[AgentConfig] | None = None,
    ) -> None:
        self._default = default_agent
        self._prefix_map: dict[str, AgentConfig] = {}

        for agent in agents or []:
            if agent.prefix:
                self._prefix_map[agent.prefix.lower()] = agent

    def resolve(self, user_text: str) -> tuple[AgentConfig, str]:
        """Determine which agent should handle a message.

        If the message starts with a known prefix (e.g. "/research query"),
        routes to that agent and strips the prefix. Otherwise routes to default.

        Returns:
            (agent_config, cleaned_user_text)
        """
        text_lower = user_text.strip().lower()
        for prefix, agent in self._prefix_map.items():
            if text_lower.startswith(prefix):
                # Strip prefix and leading whitespace
                remainder = user_text.strip()[len(prefix):].strip()
                return agent, remainder or "(no query provided)"

        return self._default, user_text

    def run(
        self,
        client: Any,
        user_text: str,
        channel: str,
        user_id: str,
        session_store: SessionStore,
        tool_registry: ToolRegistry,
        on_tool_use: OnToolUseCallback = None,
    ) -> str:
        """Resolve the agent, build the session key, and run the turn.

        Args:
            client: Portkey client instance.
            user_text: Raw user input (may include prefix).
            channel: Channel identifier (e.g. "repl", "telegram").
            user_id: User identifier for session isolation.
            session_store: Session persistence.
            tool_registry: Available tools.
            on_tool_use: Optional tool-use callback.

        Returns:
            The agent's text response.
        """
        agent, cleaned_text = self.resolve(user_text)
        session_key = f"{agent.session_prefix}:{channel}:{user_id}"

        return run_agent_turn(
            client=client,
            model=agent.model,
            system_prompt=agent.system_prompt,
            session_key=session_key,
            user_text=cleaned_text,
            session_store=session_store,
            tool_registry=tool_registry,
            on_tool_use=on_tool_use,
        )

    @property
    def agent_names(self) -> list[str]:
        """All registered agent names (default + prefix agents)."""
        names = [self._default.name]
        names.extend(a.name for a in self._prefix_map.values())
        return names

    @property
    def prefixes(self) -> list[str]:
        """All registered prefix commands."""
        return list(self._prefix_map.keys())

    @property
    def default_agent(self) -> AgentConfig:
        return self._default
