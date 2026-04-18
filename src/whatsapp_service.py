import httpx
import os
import logging

logger = logging.getLogger(__name__)

# Pointing to the local Node.js service running express
NODE_JS_BRIDGE_URL = os.getenv("NODE_JS_BRIDGE_URL", "http://127.0.0.1:3000")

async def send_whatsapp_message(to_number: str, text: str):
    """Sends a message via the local Node.js whatsapp-web.js bridge"""
    url = f"{NODE_JS_BRIDGE_URL}/send"
    payload = {
        "to": to_number,
        "text": text
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            logger.info(f"Message sent to {to_number} via Node.js bridge")
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to send message: {e.response.text if e.response else e}")
            return None

async def send_whatsapp_document(to_number: str, document_url: str, caption: str = ""):
    """
    Since whatsapp-web.js requires local file path or base64 for documents, 
    we need to implement this endpoint on Node.js side later.
    For now, we just send a notification that report is generated.
    """
    return await send_whatsapp_message(
        to_number, 
        f"Report generated: {document_url}\n{caption}\n(File sending via bridge not fully implemented yet)"
    )
