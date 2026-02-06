"""OpenClaw Bridge - Communication actions for Nexus ↔ Aries partnership"""

import httpx
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("nexus.skills.openclaw-bridge")


class OpenClawBridge:
    """Handle communication with OpenClaw Gateway API"""
    
    def __init__(self, gateway_url: str, auth_token: str):
        self.gateway_url = gateway_url.rstrip('/')
        self.auth_token = auth_token
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"Authorization": f"Bearer {auth_token}"}
        )
    
    async def _api_call(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Make authenticated API call to OpenClaw Gateway"""
        try:
            # OpenClaw Gateway API format
            url = f"{self.gateway_url}/api/gateway/tools/{tool_name}"
            headers = {
                "Authorization": f"Bearer {self.auth_token}",
                "Content-Type": "application/json"
            }
            response = await self.client.post(url, json=params, headers=headers)
            response.raise_for_status()
            result = response.json()
            
            if result.get("ok"):
                return {"success": True, "result": result.get("result", "")}
            else:
                return {"success": False, "error": result.get("error", "Unknown error")}
        except httpx.HTTPError as e:
            logger.error(f"OpenClaw API call failed: {e}")
            return {"error": str(e), "success": False}
    
    async def send_message(self, message: str, priority: str = "normal") -> str:
        """Send message to Aries via OpenClaw sessions system"""
        data = {
            "sessionKey": "main",  # Main agent session
            "message": f"[Nexus → Aries] {message}"
        }
        
        result = await self._api_call("sessions_send", data)
        
        if result.get("success"):
            return f"✅ Message sent to Aries successfully"
        else:
            return f"❌ Failed to send message: {result.get('error', 'Unknown error')}"
    
    async def notify_task_completion(self, task_description: str, result_summary: str, attachments: str = "") -> str:
        """Notify Aries of completed task with results"""
        notification = f"""🎯 **Task Completed**

**Task:** {task_description}

**Results:** {result_summary}

{f"**Attachments:** {attachments}" if attachments else ""}

Ready for next steps or handoff if needed!"""
        
        return await self.send_message(notification, "high")
    
    async def request_help(self, assistance_type: str, details: str, urgency: str = "medium") -> str:
        """Request assistance from Aries for system-level tasks"""
        urgency_emoji = {"low": "💭", "medium": "🤝", "high": "🚨"}
        
        request = f"""{urgency_emoji.get(urgency, "🤝")} **Assistance Request**

**Type:** {assistance_type}
**Details:** {details}
**Urgency:** {urgency}

Could you help with this? It's outside my current capabilities but well within yours!"""
        
        return await self.send_message(request, urgency)
    
    async def sync_shared_context(self, context_type: str, data: str) -> str:
        """Sync context data with Aries"""
        sync_msg = f"""📋 **Context Sync**

**Type:** {context_type}
**Data:** {data}

Keeping our shared understanding up to date."""
        
        return await self.send_message(sync_msg, "normal")


# ── Action Handlers (called by skills engine) ──

async def send_to_aries(params: Dict[str, str], config_manager) -> str:
    """Send direct message to Aries"""
    gateway_url = config_manager.get("OPENCLAW_GATEWAY_URL", "")
    token = config_manager.get("OPENCLAW_TOKEN", "")
    
    if not gateway_url or not token:
        return "❌ OpenClaw bridge not configured. Please set OPENCLAW_GATEWAY_URL and OPENCLAW_TOKEN in admin settings."
    
    bridge = OpenClawBridge(gateway_url, token)
    return await bridge.send_message(
        params.get("message", ""),
        params.get("priority", "normal")
    )


async def notify_completion(params: Dict[str, str], config_manager) -> str:
    """Notify Aries of task completion"""
    gateway_url = config_manager.get("OPENCLAW_GATEWAY_URL", "")
    token = config_manager.get("OPENCLAW_TOKEN", "")
    
    if not gateway_url or not token:
        return "❌ OpenClaw bridge not configured."
    
    bridge = OpenClawBridge(gateway_url, token)
    return await bridge.notify_task_completion(
        params.get("task_description", "Unknown task"),
        params.get("result_summary", "Completed successfully"),
        params.get("attachments", "")
    )


async def request_assistance(params: Dict[str, str], config_manager) -> str:
    """Request help from Aries"""
    gateway_url = config_manager.get("OPENCLAW_GATEWAY_URL", "")
    token = config_manager.get("OPENCLAW_TOKEN", "")
    
    if not gateway_url or not token:
        return "❌ OpenClaw bridge not configured."
    
    bridge = OpenClawBridge(gateway_url, token)
    return await bridge.request_help(
        params.get("assistance_type", "general"),
        params.get("details", "Need assistance"),
        params.get("urgency", "medium")
    )


async def sync_context(params: Dict[str, str], config_manager) -> str:
    """Sync context with Aries"""
    gateway_url = config_manager.get("OPENCLAW_GATEWAY_URL", "")
    token = config_manager.get("OPENCLAW_TOKEN", "")
    
    if not gateway_url or not token:
        return "❌ OpenClaw bridge not configured."
    
    bridge = OpenClawBridge(gateway_url, token)
    return await bridge.sync_shared_context(
        params.get("context_type", "general"),
        params.get("data", "")
    )