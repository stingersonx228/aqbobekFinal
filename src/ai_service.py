from groq import AsyncGroq
import json
import re
import os
import logging

logger = logging.getLogger(__name__)

GROQ_KEY = os.getenv("GROQ_KEY", "YOUR_GROQ_KEY")
client = AsyncGroq(api_key=GROQ_KEY)

SYSTEM_PROMPT = """You are the Senior AI Orchestrator for 'Aqbobek Lyceum'.
Your task is to parse unstructured messages from staff and route them to the correct department.

Return ONLY a valid JSON object. No markdown, no text.

CATEGORIES & FIELDS:

1. canteen (Attendance)
   - class: string (e.g., "10A", "7C")
   - total: number
   - sick: number
   - competition: number

2. substitution (Teacher Absence)
   - teacher_name: string
   - day: string

3. maintenance (Facilities/Repairs)
   - location: string
   - issue: string (e.g., "broken door", "leaking tap")
   - priority: "low" | "medium" | "high"

4. it_support (Tech/IT Issues)
   - location: string
   - device: string (e.g., "projector", "Wi-Fi", "laptop")
   - issue: string
   - priority: "medium" | "high"

5. logistics (Supply/Moving requests)
   - location: string
   - item: string (e.g., "water", "paper", "chairs")
   - quantity: string
   - action: "bring" | "remove" | "move"

6. emergency (Security/Medical/Safety)
   - location: string
   - type: "medical" | "security" | "safety"
   - description: string
   - priority: "CRITICAL"

7. task (General Administration)
   - assignee: string
   - action: string

8. spam (Irrelevant/Greeting)

ADDITIONAL GLOBAL FIELDS (Always include these):
- sender_role: string (e.g., "Учитель математики", "Завхоз", "Охрана", "Директор") - Infer from text or context.
- is_important: boolean (True if it's an emergency, serious maintenance issue, or direct order).

STRATEGY:
- If someone says "projector broken", it's 'it_support'.
- If someone says "bring water", it's 'logistics'.
- If someone says "student fainted", it's 'emergency'.
- Be smart: Infer location from context if possible.
- Default priority to 'medium' unless it sounds urgent.
"""

async def extract_with_ai(text: str) -> dict:
    """Extract structured data using Groq Llama-3.3-70b"""
    try:
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Message: {text}"}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        raw_text = response.choices[0].message.content.strip()
        return json.loads(raw_text)
    except Exception as e:
        logger.error(f"Groq Extraction Error: {e}")
        return {"type": "spam"}
