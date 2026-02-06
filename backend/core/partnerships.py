"""Partner agent registry and inter-agent messaging for Nexus <-> Aries."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from schemas.partnerships import PartnerAgent, AgentMessage

logger = logging.getLogger("nexus.partnerships")


class PartnerRegistry:
    """Manages partner agent connections, health, and messaging."""

    def __init__(self, config: Any):
        self.config = config
        self._agents: dict[str, PartnerAgent] = {}
        self._health_tasks: dict[str, asyncio.Task] = {}

    async def register(self, agent: PartnerAgent) -> None:
        """Register a partner agent."""
        self._agents[agent.name] = agent
        logger.info(f"Registered partner agent: {agent.name} at {agent.gateway_url}")

    async def unregister(self, name: str) -> None:
        """Remove a partner agent."""
        if name in self._health_tasks:
            self._health_tasks[name].cancel()
            del self._health_tasks[name]
        self._agents.pop(name, None)
        logger.info(f"Unregistered partner agent: {name}")

    async def list_agents(self) -> list[PartnerAgent]:
        """List all registered partner agents."""
        return list(self._agents.values())

    async def get_agent(self, name: str) -> PartnerAgent | None:
        """Get a specific partner agent."""
        return self._agents.get(name)

    async def discover(self) -> list[PartnerAgent]:
        """Discover partner agents (from config or network)."""
        # Check config for pre-configured partners
        gateway_url = self.config.get("OPENCLAW_GATEWAY_URL", "") if self.config else ""
        token = self.config.get("OPENCLAW_TOKEN", "") if self.config else ""

        if gateway_url and token:
            agent = PartnerAgent(
                name="aries",
                gateway_url=gateway_url,
                auth_token=token,
                capabilities=["file_management", "email", "reminders", "system_control"],
                status="offline",
            )
            if "aries" not in self._agents:
                await self.register(agent)

        return await self.list_agents()

    async def health_check(self, agent_name: str) -> bool:
        """Check if a partner agent is reachable."""
        agent = self._agents.get(agent_name)
        if not agent:
            return False

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {}
                if agent.auth_token:
                    headers["Authorization"] = f"Bearer {agent.auth_token}"
                resp = await client.get(
                    f"{agent.gateway_url}/api/health",
                    headers=headers,
                )
                if resp.status_code == 200:
                    agent.status = "online"
                    agent.last_seen = datetime.now(timezone.utc)
                    return True
                else:
                    agent.status = "degraded"
                    return False
        except Exception as e:
            logger.warning(f"Health check failed for {agent_name}: {e}")
            agent.status = "offline"
            return False

    async def send_message(self, msg: AgentMessage) -> AgentMessage:
        """Send a message to a partner agent with retry logic."""
        agent = self._agents.get(msg.recipient)
        if not agent:
            return AgentMessage(
                sender="nexus",
                recipient=msg.sender,
                type="task_result",
                payload={"error": f"Agent '{msg.recipient}' not found"},
                reply_to=msg.id,
            )

        max_retries = 3
        delays = [1, 2, 4]  # exponential backoff

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    headers = {"Content-Type": "application/json"}
                    if agent.auth_token:
                        headers["Authorization"] = f"Bearer {agent.auth_token}"

                    resp = await client.post(
                        f"{agent.gateway_url}/api/gateway/message",
                        json=msg.model_dump(mode="json"),
                        headers=headers,
                    )
                    resp.raise_for_status()
                    data = resp.json()

                    agent.status = "online"
                    agent.last_seen = datetime.now(timezone.utc)

                    return AgentMessage(
                        sender=msg.recipient,
                        recipient="nexus",
                        type="task_result",
                        payload=data,
                        reply_to=msg.id,
                    )

            except Exception as e:
                logger.warning(
                    f"Message to {msg.recipient} failed (attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(delays[attempt])
                else:
                    agent.status = "offline"
                    return AgentMessage(
                        sender="nexus",
                        recipient=msg.sender,
                        type="task_result",
                        payload={"error": f"Failed after {max_retries} attempts: {e}"},
                        reply_to=msg.id,
                    )

    async def negotiate_capabilities(self, agent_name: str) -> list[str]:
        """Query what capabilities a partner agent has."""
        msg = AgentMessage(
            sender="nexus",
            recipient=agent_name,
            type="capability_query",
            payload={"query": "list_capabilities"},
        )
        response = await self.send_message(msg)
        return response.payload.get("capabilities", [])

    async def handoff_task(
        self,
        agent_name: str,
        task_description: str,
        context: dict | None = None,
    ) -> AgentMessage:
        """Delegate work to a partner agent."""
        msg = AgentMessage(
            sender="nexus",
            recipient=agent_name,
            type="handoff",
            payload={
                "task": task_description,
                "context": context or {},
            },
        )
        return await self.send_message(msg)

    async def receive_handoff(self, msg: AgentMessage) -> AgentMessage:
        """Accept delegated work from a partner agent."""
        logger.info(f"Received handoff from {msg.sender}: {msg.payload.get('task', '')}")
        return AgentMessage(
            sender="nexus",
            recipient=msg.sender,
            type="task_result",
            payload={"status": "accepted", "message": "Task received and queued"},
            reply_to=msg.id,
        )
