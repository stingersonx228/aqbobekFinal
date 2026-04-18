from groq import AsyncGroq
import json
import os
import logging
import base64
import tempfile

logger = logging.getLogger(__name__)

GROQ_KEY = os.getenv("GROQ_KEY")
client = AsyncGroq(api_key=GROQ_KEY)

SYSTEM_PROMPT = """You are the Senior AI Orchestrator for 'Aqbobek Lyceum'.
Parse staff messages and return ONLY a valid flat JSON object.

CRITICAL RULES:
1. ALWAYS include "type" as a TOP-LEVEL field.
2. NEVER nest fields inside a category key.
3. No markdown, no code blocks, just raw JSON.
4. ALWAYS extract text values in the ORIGINAL LANGUAGE of the message (Russian/Kazakh). DO NOT translate words like "сломался" to "broken".

CORRECT example: {"type": "canteen", "class": "10A", "total": 25, "sick": 2, "competition": 0, "sender_role": "Teacher", "is_important": false}
WRONG example:   {"canteen": {"class": "10A", ...}}  <-- NEVER do this!

TYPES AND THEIR FIELDS:

type: "canteen" - when teacher reports class attendance
  - class (string): class name e.g. "10A", "7B"
  - total (number): total students
  - sick (number): sick students
  - competition (number): students at competitions

type: "substitution" - teacher is absent
  - teacher_name (string)
  - day (string)

type: "maintenance" - physical repair needed
  - location (string): room or place
  - issue (string): what is broken
  - priority: "low" | "medium" | "high"

type: "it_support" - tech problem
  - location (string)
  - device (string): projector, wifi, laptop, etc
  - issue (string)
  - priority: "medium" | "high"

type: "logistics" - supply or moving request
  - location (string)
  - item (string): water, chairs, paper, etc
  - quantity (string)
  - action: "bring" | "remove" | "move"

type: "emergency" - danger, medical, security
  - location (string)
  - description (string)
  - priority: "CRITICAL"

type: "task" - general admin task assignment
  - assignee (string)
  - action (string)

type: "multi_task" - when a message contains MULTIPLE distinct tasks (e.g., from voice notes)
  - tasks (array of objects): each object must have "type" (like "task" or "maintenance") and its specific fields.

type: "bureaucracy" - request to draft official documents/orders (Приказ)
  - document_type (string): e.g., "130-й регламент", "Отстранение", "Приказ №76"
  - target (string): who it affects (class or person)
  - reason (string): why it's needed

type: "lenta" - request to auto-balance a Singapore Lenta schedule
  - target_group (string): e.g., "8-е классы", "3-е классы"
  - subject (string): e.g., "Английский", "Математика"

type: "spam" - greetings, irrelevant, unknown

ALWAYS ADD THESE GLOBAL FIELDS:
  - sender_role (string): infer from context e.g. "Math Teacher", "Security", "Director"
  - is_important (boolean): true for emergency/urgent issues

DETECTION RULES:
- Class name + numbers → canteen
- Projector/wifi/laptop broken → it_support
- Door/tap/window/furniture → maintenance
- Bring/move/deliver → logistics
- Fainted/fight/fire/danger → emergency
- Приказ, документ, регламент → bureaucracy
- Лента, уровневая группа, перемешать классы → lenta
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
        result = json.loads(raw_text)

        # Safety net: if AI forgot to add 'type' but put it as a key
        if "type" not in result:
            for possible_type in ["canteen", "substitution", "maintenance", "it_support", "logistics", "emergency", "task", "bureaucracy", "lenta", "spam"]:
                if possible_type in result:
                    nested = result.pop(possible_type)
                    result["type"] = possible_type
                    result.update(nested)
                    break
            else:
                result["type"] = result.get("category", "spam")

        return result

    except Exception as e:
        logger.error(f"Groq Extraction Error: {e}")
        return {"type": "spam"}

async def transcribe_audio(audio_base64: str, mimetype: str) -> str:
    """Transcribe base64 audio using Groq Whisper API (whisper-large-v3-turbo)"""
    try:
        ext = ".ogg"
        if "mp4" in mimetype: ext = ".m4a"
        elif "webm" in mimetype: ext = ".webm"
        elif "wav" in mimetype: ext = ".wav"
        
        audio_data = base64.b64decode(audio_base64)
        
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name
            
        with open(tmp_path, "rb") as file:
            transcription = await client.audio.transcriptions.create(
              file=(os.path.basename(tmp_path), file.read()),
              model="whisper-large-v3-turbo"
            )
            
        os.unlink(tmp_path)
        return transcription.text
    except Exception as e:
        logger.error(f"Whisper Transcription Error: {e}")
        return ""
