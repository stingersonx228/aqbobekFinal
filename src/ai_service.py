from groq import AsyncGroq
import json
import re
import os
import logging

logger = logging.getLogger(__name__)

GROQ_KEY = os.getenv("GROQ_KEY", "YOUR_GROQ_KEY")
client = AsyncGroq(api_key=GROQ_KEY)

SYSTEM_PROMPT = """You are a strict message classification system for a school dashboard.

Task: Analyze the input message and return ONLY a valid JSON object.
Do NOT include any explanations, comments, or extra text.
Do NOT use markdown. Output must be pure JSON.

Categories:
1. canteen — Reports about student attendance affecting meals.
Required fields: 
- class (string)
- total (number)
- sick (number, default 0)
- competition (number, default 0)

2. incident — Reports of damage or broken items.
Required fields: 
- location (string)
- issue (string)
- reporter (string, try to extract name or role like 'Учитель 1А', default to 'Неизвестный')
- assignedTo (string, usually 'Завхоз' or 'IT отдел')

3. task — Instructions or assignments for staff.
Required fields: 
- assignee (string)
- action (string)

4. spam — Any message that does not match the above categories.

Rules:
- Always return exactly one JSON object
- No extra text under any circumstances
- If required data is missing and cannot be inferred, return {"type":"spam"}
"""

async def extract_with_gemini(text: str) -> dict:
    """Extract structured data from text using Groq (llama-3.3-70b)"""
    try:
        response = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Text: {text}"}
            ],
            temperature=0.1,
            max_tokens=256,
        )
        
        raw_text = response.choices[0].message.content.strip()
        raw_text = raw_text.replace('```json', '').replace('```', '').strip()
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        
        if json_match:
            return json.loads(json_match.group())
        return {"type": "spam"}
    except Exception as e:
        logger.error(f"Groq Extraction Error: {e}")
        return {"type": "spam"}
