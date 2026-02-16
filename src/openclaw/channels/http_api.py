"""HTTP REST API channel — exposes the agent as a web API.

Endpoints:
    POST /chat    — Send a message, get a response
    GET  /health  — Health check

Requires Flask: install with `pip install openclaw-clone[http]`
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from openclaw.agent.router import AgentRouter
from openclaw.channels.base import ChannelAdapter
from openclaw.queue.command_queue import CommandQueue
from openclaw.session.store import SessionStore
from openclaw.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class HttpApiChannel(ChannelAdapter):
    """Flask-based HTTP API channel.

    Usage::

        channel = HttpApiChannel(
            router=router,
            session_store=session_store,
            tool_registry=tool_registry,
            command_queue=command_queue,
            port=5000,
        )
        channel.start()  # Starts Flask in a thread
    """

    def __init__(
        self,
        router: AgentRouter,
        session_store: SessionStore,
        tool_registry: ToolRegistry,
        command_queue: CommandQueue,
        host: str = "0.0.0.0",
        port: int = 5000,
    ) -> None:
        self._router = router
        self._session_store = session_store
        self._tool_registry = tool_registry
        self._command_queue = command_queue
        self._host = host
        self._port = port
        self._thread: threading.Thread | None = None
        self._app: Any = None

    @property
    def name(self) -> str:
        return "http"

    def _create_app(self):
        """Create the Flask application with routes."""
        try:
            from flask import Flask, jsonify, request
        except ImportError:
            raise ImportError(
                "Flask is required for the HTTP channel. "
                "Install with: pip install openclaw-clone[http]"
            )

        app = Flask("openclaw-http")

        @app.route("/health", methods=["GET"])
        def health():
            return jsonify({"status": "ok", "agents": self._router.agent_names})

        @app.route("/chat", methods=["POST"])
        def chat():
            data = request.get_json(silent=True) or {}
            user_text = data.get("message", "").strip()
            user_id = data.get("user_id", "anonymous")

            if not user_text:
                return jsonify({"error": "message is required"}), 400

            session_key_prefix = self._router.resolve(user_text)[0].session_prefix
            session_key = f"{session_key_prefix}:http:{user_id}"

            try:
                with self._command_queue.lock(session_key):
                    response = self._router.run(
                        client=self._get_client(),
                        user_text=user_text,
                        channel="http",
                        user_id=user_id,
                        session_store=self._session_store,
                        tool_registry=self._tool_registry,
                    )
                return jsonify({"response": response})
            except Exception as e:
                logger.exception("HTTP chat error")
                return jsonify({"error": str(e)}), 500

        @app.route("/sessions", methods=["GET"])
        def list_sessions():
            sessions = self._session_store.list_sessions()
            return jsonify({"sessions": sessions})

        self._app = app
        return app

    def _get_client(self):
        """Lazy-create the Portkey client."""
        from openclaw.config import get_portkey_client
        return get_portkey_client()

    def start(self) -> None:
        """Start Flask in a background thread."""
        app = self._create_app()

        def _run():
            app.run(host=self._host, port=self._port, debug=False, use_reloader=False)

        self._thread = threading.Thread(target=_run, daemon=True, name="http-channel")
        self._thread.start()
        logger.info("HTTP API started on %s:%d", self._host, self._port)

    def stop(self) -> None:
        """Stop the HTTP server (daemon thread dies with process)."""
        self._thread = None
        logger.info("HTTP API stopped")

    @property
    def app(self):
        """Expose the Flask app for testing."""
        if self._app is None:
            self._create_app()
        return self._app
