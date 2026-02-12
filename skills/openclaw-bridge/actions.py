"""OpenClaw Bridge - Communication actions for Nexus <-> Aries partnership.

Enhanced with typed messages, retry logic with exponential backoff,
and health check support.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

import httpx

logger = logging.getLogger("nexus.skills.openclaw-bridge")


class OpenClawBridge:
    """Handle communication with OpenClaw Gateway API."""

    def __init__(self, gateway_url: str, auth_token: str):
        self.gateway_url = gateway_url.rstrip('/')
        self.auth_token = auth_token
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"Authorization": f"Bearer {auth_token}"}
        )

    async def _api_call(
        self,
        tool_name: str,
        params: Dict[str, Any],
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """Make authenticated API call with exponential backoff retry."""
        delays = [1, 2, 4]

        for attempt in range(max_retries):
            try:
                url = f"{self.gateway_url}/api/gateway/tools/{tool_name}"
                headers = {
                    "Authorization": f"Bearer {self.auth_token}",
                    "Content-Type": "application/json",
                }
                response = await self.client.post(url, json=params, headers=headers)
                response.raise_for_status()
                result = response.json()

                if result.get("ok"):
                    return {"success": True, "result": result.get("result", "")}
                else:
                    return {"success": False, "error": result.get("error", "Unknown error")}

            except httpx.HTTPError as e:
                logger.warning(
                    f"OpenClaw API call failed (attempt {attempt + 1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(delays[attempt])
                else:
                    logger.error(f"OpenClaw API call failed after {max_retries} attempts: {e}")
                    return {"error": str(e), "success": False}

    async def health_check(self) -> Dict[str, Any]:
        """Check if the OpenClaw gateway is reachable."""
        try:
            response = await self.client.get(
                f"{self.gateway_url}/api/health",
                headers={"Authorization": f"Bearer {self.auth_token}"},
                timeout=10.0,
            )
            if response.status_code == 200:
                return {"status": "online", "details": response.json()}
            return {"status": "degraded", "code": response.status_code}
        except Exception as e:
            return {"status": "offline", "error": str(e)}

    async def send_message(self, message: str, priority: str = "normal") -> str:
        """Send message to Aries via OpenClaw sessions system."""
        data = {
            "sessionKey": "main",
            "message": f"[Nexus -> Aries] {message}",
        }
        result = await self._api_call("sessions_send", data)
        if result.get("success"):
            return "Message sent to Aries successfully"
        return f"Failed to send message: {result.get('error', 'Unknown error')}"

    async def notify_task_completion(
        self, task_description: str, result_summary: str, attachments: str = "",
    ) -> str:
        """Notify Aries of completed task with results."""
        notification = (
            f"**Task Completed**\n\n"
            f"**Task:** {task_description}\n\n"
            f"**Results:** {result_summary}"
        )
        if attachments:
            notification += f"\n\n**Attachments:** {attachments}"
        notification += "\n\nReady for next steps or handoff if needed!"
        return await self.send_message(notification, "high")

    async def request_help(
        self, assistance_type: str, details: str, urgency: str = "medium",
    ) -> str:
        """Request assistance from Aries for system-level tasks."""
        request = (
            f"**Assistance Request**\n\n"
            f"**Type:** {assistance_type}\n"
            f"**Details:** {details}\n"
            f"**Urgency:** {urgency}\n\n"
            f"Could you help with this?"
        )
        return await self.send_message(request, urgency)

    async def sync_shared_context(self, context_type: str, data: str) -> str:
        """Sync context data with Aries."""
        sync_msg = (
            f"**Context Sync**\n\n"
            f"**Type:** {context_type}\n"
            f"**Data:** {data}\n\n"
            f"Keeping our shared understanding up to date."
        )
        return await self.send_message(sync_msg, "normal")

    async def close(self) -> None:
        """Clean up HTTP client."""
        await self.client.aclose()


def _get_bridge(params: Dict[str, Any]) -> OpenClawBridge | None:
    """Create bridge from config, handling both old and new param styles."""
    config = params.get("_config")
    if not config:
        return None
    gateway_url = config.get("OPENCLAW_GATEWAY_URL", "")
    token = config.get("OPENCLAW_TOKEN", "")
    if not gateway_url or not token:
        return None
    return OpenClawBridge(gateway_url, token)


# ── Action Handlers (called by skills engine) ──

async def send_to_aries(params: Dict[str, str]) -> str:
    """Send direct message to Aries."""
    bridge = _get_bridge(params)
    if not bridge:
        return "OpenClaw bridge not configured. Please set OPENCLAW_GATEWAY_URL and OPENCLAW_TOKEN in admin settings."
    try:
        return await bridge.send_message(
            params.get("message", ""),
            params.get("priority", "normal"),
        )
    finally:
        await bridge.close()


async def notify_completion(params: Dict[str, str]) -> str:
    """Notify Aries of task completion."""
    bridge = _get_bridge(params)
    if not bridge:
        return "OpenClaw bridge not configured."
    try:
        return await bridge.notify_task_completion(
            params.get("task_description", "Unknown task"),
            params.get("result_summary", "Completed successfully"),
            params.get("attachments", ""),
        )
    finally:
        await bridge.close()


async def request_assistance(params: Dict[str, str]) -> str:
    """Request help from Aries."""
    bridge = _get_bridge(params)
    if not bridge:
        return "OpenClaw bridge not configured."
    try:
        return await bridge.request_help(
            params.get("assistance_type", "general"),
            params.get("details", "Need assistance"),
            params.get("urgency", "medium"),
        )
    finally:
        await bridge.close()


async def sync_context(params: Dict[str, str]) -> str:
    """Sync context with Aries."""
    bridge = _get_bridge(params)
    if not bridge:
        return "OpenClaw bridge not configured."
    try:
        return await bridge.sync_shared_context(
            params.get("context_type", "general"),
            params.get("data", ""),
        )
    finally:
        await bridge.close()
