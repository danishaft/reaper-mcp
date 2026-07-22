"""Bridge client interface."""

from typing import Any, Protocol

from reaper_mcp.models.bridge import BridgeResponse, CommandEnvelope, CommandOptions


class BridgeClient(Protocol):
    """Protocol implemented by bridge transports."""

    async def execute(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        options: CommandOptions | None = None,
    ) -> BridgeResponse:
        """Build and send a command envelope."""

    async def send(self, envelope: CommandEnvelope) -> BridgeResponse:
        """Send a command envelope and return the bridge response."""

    async def get_job(self, job_id: str) -> BridgeResponse | None:
        """Return a completed asynchronous bridge job, if available."""
