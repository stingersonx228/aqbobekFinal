from fastapi import FastAPI, Request, BackgroundTasks, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from datetime import datetime, timezone
from dotenv import load_dotenv
import os
import logging
import uuid
import json
import re

# Load env BEFORE local imports
load_dotenv()

from src.database import engine, Base, get_db, AsyncSessionLocal
from src.models import IncidentRecord, CanteenRecord, TaskRecord, ServiceRequest
from src.schemas import NutritionReportResponse, AbsentDetails, IncidentsResponse, IncidentDetail, TasksResponse, TaskDetail
from src.ai_service import extract_with_ai
from src.whatsapp_service import send_whatsapp_message
from src.export_service import generate_excel_report
from src.scheduler_service import scheduler
from src.notification_service import send_unified_reply, notify_all_platforms

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Aqbobek Lyceum AI OS")

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- WebSocket Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"WebSocket send error: {e}")

manager = ConnectionManager()

@app.on_event("startup")
async def startup_event():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Aqbobek OS Initialized.")

@app.get("/")
def read_root():
    return {"status": "Aqbobek AI OS is running"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# --- API Endpoints ---

@app.get("/api/v1/nutrition/today")
async def get_nutrition_today(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(
        func.sum(CanteenRecord.sick_students).label('total_sick'),
        func.sum(CanteenRecord.competition_students).label('total_comp'),
        func.count(CanteenRecord.id).label('messages_count')
    ))
    row = result.fetchone()
    return {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "totalVseobuch": 400,
        "absentDetails": {"sick_count": row.total_sick or 0, "competition_count": row.total_comp or 0},
        "rawMessagesParsed": row.messages_count or 0
    }

@app.get("/api/v1/incidents/active")
async def get_active_incidents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(IncidentRecord).order_by(IncidentRecord.created_at.desc()))
    incidents = result.scalars().all()
    return {"incidents": [inc.issue for inc in incidents]}

@app.get("/api/v1/schedule/substitution")
async def get_latest_substitution(teacher: str, day: str = "Дүйсенбі"):
    return scheduler.find_replacement(teacher, day)

# --- KILLER FEATURE: Command Processing ---

async def handle_commands(from_number: str, text: str) -> bool:
    cmd = text.strip().lower()
    
    if cmd.startswith("/free"):
        # Example: /free 09:05-09:50
        parts = text.split(" ", 1)
        time_slot = parts[1] if len(parts) > 1 else "08:00-08:45"
        free = scheduler.find_free_teachers("Дүйсенбі", time_slot)
        
        reply = f"🟢 Свободные учителя ({time_slot}):\n"
        for t in free[:10]:
            reply += f"- {t['name']}\n"
        await send_unified_reply(from_number, reply)
        return True
        
    if cmd == "/report":
        await send_unified_reply(from_number, "⏳ Генерирую Excel-отчет...")
        async with AsyncSessionLocal() as db:
            filepath = await generate_excel_report(db)
        await send_unified_reply(from_number, f"📊 Отчет готов! Путь: {filepath}")
        return True
        
    return False

# --- Main Logic ---

async def process_whatsapp_message(message_data: dict):
    try:
        from_number = message_data.get("from")
        text_body = message_data.get("body", "")
        if not text_body: return

        # 1. Handle Commands
        if await handle_commands(from_number, text_body):
            return

        # 2. AI Extraction
        parsed_data = await extract_with_ai(text_body)
        data_type = parsed_data.get("type")
        broadcast_event = None

        async with AsyncSessionLocal() as db:
            if data_type in ["it_support", "maintenance", "logistics", "emergency"]:
                desc = parsed_data.get("issue") or parsed_data.get("description") or parsed_data.get("item")
                priority = parsed_data.get("priority", "medium")
                
                new_request = ServiceRequest(
                    category=data_type,
                    location=parsed_data.get("location", "unknown"),
                    description=desc,
                    priority=priority
                )
                db.add(new_request)
                await db.commit()
                
                # KILLER FEATURE: Emergency Multi-Platform Broadcast
                if data_type == "emergency":
                    await notify_all_platforms(f"ВНИМАНИЕ! {desc} в {new_request.location}", priority="CRITICAL")
                
                # Reply
                replies = {
                    "it_support": f"⚙️ IT-служба уведомлена: {desc}.",
                    "emergency": f"🚨 СИГНАЛ ТРЕВОГИ ПРИНЯТ! Помощь направлена в {new_request.location}.",
                    "logistics": f"📦 Запрос на логистику ({desc}) принят.",
                    "maintenance": f"🛠 Заявка на ремонт ({desc}) создана."
                }
                await send_unified_reply(from_number, replies.get(data_type, "Заявка принята."))
                broadcast_event = {"type": "NEW_SERVICE_REQUEST", "category": data_type}

            elif data_type == "canteen":
                new_record = CanteenRecord(
                    class_name=parsed_data.get("class", "school"),
                    total_students=parsed_data.get("total", 0),
                    sick_students=parsed_data.get("sick", 0),
                    competition_students=parsed_data.get("competition", 0)
                )
                db.add(new_record)
                await db.commit()
                broadcast_event = {"type": "NUTRITION_UPDATED"}

            elif data_type == "substitution":
                teacher_name = parsed_data.get("teacher_name")
                sub_results = scheduler.find_replacement(teacher_name, "Дүйсенбі")
                
                if "replacements" in sub_results:
                    reply = f"🚨 Учитель {sub_results['sick_teacher']} отсутствует.\n"
                    for rep in sub_results["replacements"]:
                        reply += f"\n📖 {rep['original_lesson']}\n"
                        if rep["candidates"]:
                            reply += f"✅ Замена: {rep['candidates'][0]['name']}\n"
                    await send_unified_reply(from_number, reply)
                    broadcast_event = {"type": "SUBSTITUTION_FOUND", "data": sub_results}

        if broadcast_event:
            await manager.broadcast(broadcast_event)

    except Exception as e:
        logger.error(f"Error: {e}")

@app.post("/internal-webhook")
async def internal_webhook_handler(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    background_tasks.add_task(process_whatsapp_message, data)
    return JSONResponse(content={"status": "received"})
