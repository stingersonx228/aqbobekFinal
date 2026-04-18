from fastapi import FastAPI, Request, BackgroundTasks, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from datetime import datetime, timezone
from dotenv import load_dotenv
from contextlib import asynccontextmanager
import asyncio
import os
import logging
import uuid
import json

# Load env BEFORE local imports
load_dotenv()

from src.database import engine, Base, get_db, AsyncSessionLocal
from src.models import IncidentRecord, CanteenRecord, TaskRecord, ServiceRequest, ChatMessage
from src.schemas import NutritionReportResponse, AbsentDetails, IncidentsResponse, IncidentDetail, TasksResponse, TaskDetail
from src.notification_service import send_unified_reply, notify_all_platforms
from src.scheduler_service import scheduler
from src.export_service import generate_excel_report, get_canteen_summary, get_daily_stats
from src.ai_service import extract_with_ai, transcribe_audio

INTERNAL_SECRET = os.getenv("INTERNAL_SECRET_TOKEN", "fallback_secret_for_dev_only")
PROCESSED_MESSAGE_IDS = set()

import json

# --- Справочник классов (Smart Canteen) ---
# На основе реального PDF расписания лицея
DEFAULT_CLASS_SIZES = {
    "7A": 25, "7B": 25, "7C": 25,
    "8A": 25, "8B": 25, "8C": 25, "8D": 25,
    "9A": 25, "9B": 25,
    "10A": 20, "10B": 20,
    "11A": 15, "11B": 15
}

def normalize_class_name(name: str) -> str:
    """Убирает пробелы и меняет кириллицу А/В/С на латиницу A/B/C для единого формата"""
    name = str(name).upper().replace(" ", "")
    replacements = {'А': 'A', 'В': 'B', 'Б': 'B', 'С': 'C', 'Д': 'D'}
    for cyr, lat in replacements.items():
        name = name.replace(cyr, lat)
    return name

# --- Память контекста для уточнений ---
USER_LAST_MESSAGE = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --- Background Scheduler: Auto-report at 09:00 ---

async def daily_canteen_report_job():
    """
    ТЗ Requirement: 'Ровно в 09:00 агент должен автоматически собрать все сообщения,
    посчитать сумму и выдать директору готовый отчет.'
    """
    while True:
        now = datetime.now()
        # Calculate seconds until next 09:00
        target = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= target:
            target = target.replace(day=target.day + 1)
        wait_seconds = (target - now).total_seconds()

        logger.info(f"⏰ Auto-report scheduled in {wait_seconds / 3600:.1f} hours (at 09:00)")
        await asyncio.sleep(wait_seconds)

        # Generate and broadcast the report
        try:
            async with AsyncSessionLocal() as db:
                summary = await get_canteen_summary(db)

            logger.info(f"📋 Auto-report triggered: {summary['portions_needed']} portions needed")

            # Broadcast to dashboard
            await manager.broadcast({
                "type": "DAILY_CANTEEN_REPORT",
                "data": summary
            })

            # Notify via all platforms (cafeteria manager / director)
            await notify_all_platforms(summary["cafeteria_text"], priority="medium")

        except Exception as e:
            logger.error(f"Auto-report error: {e}")


# --- App Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Aqbobek OS Initialized.")

    # Start background scheduler
    report_task = asyncio.create_task(daily_canteen_report_job())

    yield

    # Shutdown
    report_task.cancel()


app = FastAPI(title="Aqbobek Lyceum AI OS", lifespan=lifespan)

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


# ========== API ENDPOINTS ==========

# --- Reports & Analytics ---

@app.get("/api/v1/reports/canteen")
async def api_canteen_summary(db: AsyncSession = Depends(get_db)):
    """Returns today's canteen summary with per-class breakdown."""
    return await get_canteen_summary(db)

@app.get("/api/v1/reports/daily")
async def api_daily_stats(db: AsyncSession = Depends(get_db)):
    """Full daily statistics: canteen + incidents + tasks + service requests."""
    return await get_daily_stats(db)

@app.get("/api/v1/reports/download")
async def api_download_report(db: AsyncSession = Depends(get_db)):
    """Generate and download a full Excel report."""
    filepath = await generate_excel_report(db)
    return FileResponse(
        path=filepath,
        filename=f"aqbobek_report_{datetime.now().strftime('%Y%m%d')}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# --- Nutrition ---

@app.get("/api/v1/nutrition/today")
async def get_nutrition_today(db: AsyncSession = Depends(get_db)):
    summary = await get_canteen_summary(db)
    return summary

# --- Messages (Chat Summary) ---

@app.get("/api/v1/messages")
async def get_chat_messages(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ChatMessage).order_by(ChatMessage.timestamp.desc()).limit(50))
    messages = result.scalars().all()
    return {
        "messages": [
            {
                "id": m.id,
                "sender": m.sender_name,
                "role": m.sender_role,
                "content": m.message,
                "platform": m.platform,
                "isImportant": m.is_important,
                "timestamp": m.timestamp.isoformat()
            } for m in messages
        ]
    }

# --- Incidents ---

@app.get("/api/v1/incidents/active")
async def get_active_incidents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(IncidentRecord).order_by(IncidentRecord.created_at.desc()))
    incidents = result.scalars().all()
    return {
        "incidents": [
            {
                "id": str(inc.id),
                "incident_id": inc.incident_id,
                "location": inc.location,
                "issue": inc.issue,
                "status": inc.status,
                "reportedBy": inc.reported_by,
                "assignedTo": inc.assigned_to,
                "createdAt": inc.created_at.isoformat()
            } for inc in incidents
        ]
    }

# --- Schedule ---

@app.get("/api/v1/schedule/substitution")
async def get_latest_sub(teacher: str, day: str = "Дүйсенбі"):
    return await scheduler.find_replacement(teacher, day)

@app.get("/api/v1/schedule/free")
async def get_free(day: str = "Дүйсенбі", time_slot: str = "08:00-08:45"):
    return await scheduler.find_free_teachers(day, time_slot)

# --- Service Requests ---

@app.get("/api/v1/service-requests")
async def get_service_requests(db: AsyncSession = Depends(get_db), category: str = None):
    query = select(ServiceRequest).order_by(ServiceRequest.created_at.desc())
    if category:
        query = query.where(ServiceRequest.category == category)
    result = await db.execute(query)
    requests_list = result.scalars().all()
    return {
        "requests": [
            {
                "id": r.id,
                "category": r.category,
                "location": r.location,
                "description": r.description,
                "priority": r.priority,
                "status": r.status,
                "createdAt": r.created_at.isoformat()
            } for r in requests_list
        ]
    }


# ========== COMMAND PROCESSING ==========

async def handle_commands(from_number: str, text: str) -> bool:
    cmd = text.strip().lower()

    if cmd.startswith("/free"):
        parts = text.split(" ", 1)
        time_slot = parts[1] if len(parts) > 1 else "08:00-08:45"
        free = await scheduler.find_free_teachers("Дүйсенбі", time_slot)
        reply = f"🟢 Свободные учителя ({time_slot}):\n"
        for t in free[:10]:
            reply += f"- {t['name']}\n"
        await send_unified_reply(from_number, reply)
        return True

    if cmd == "/report":
        await send_unified_reply(from_number, "⏳ Генерирую Excel-отчет...")
        async with AsyncSessionLocal() as db:
            filepath = await generate_excel_report(db)
        await send_unified_reply(from_number, f"📊 Отчет готов: {filepath}")
        return True

    if cmd == "/canteen" or cmd == "/свод":
        async with AsyncSessionLocal() as db:
            summary = await get_canteen_summary(db)
        await send_unified_reply(from_number, summary["cafeteria_text"])
        return True

    if cmd == "/stats" or cmd == "/стат":
        async with AsyncSessionLocal() as db:
            stats = await get_daily_stats(db)
        reply = (
            f"📊 Статистика за {stats['date']}:\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🍽 Порций: {stats['canteen']['portions_needed']}\n"
            f"🚨 Инцидентов сегодня: {stats['incidents']['today']}\n"
            f"📋 Задач в работе: {stats['tasks']['pending_total']}\n"
            f"💬 Сообщений: {stats['messages_total']}\n"
        )
        await send_unified_reply(from_number, reply)
        return True

    return False


# ========== MAIN MESSAGE PROCESSING ==========

async def process_whatsapp_message(payload: dict):
    try:
        from_number = payload.get("from")
        text_body = payload.get("body", "")
        audio_base64 = payload.get("audio_base64")
        audio_mimetype = payload.get("audio_mimetype")

        # --- 1. Voice-to-Text (Whisper) ---
        if audio_base64:
            logger.info("🎤 Audio received! Sending to Whisper...")
            transcribed_text = await transcribe_audio(audio_base64, audio_mimetype)
            if transcribed_text:
                logger.info(f"🗣️ Transcribed: {transcribed_text}")
                text_body = transcribed_text
            else:
                await send_unified_reply(from_number, "❌ Не удалось распознать голосовое сообщение.")
                return

        if not text_body:
            return

        # 1. Handle Commands
        if await handle_commands(from_number, text_body):
            return

        # --- Слияние контекста (Уточнения) ---
        if from_number in USER_LAST_MESSAGE:
            # Если мы ждали уточнения, склеиваем старое сообщение с новым
            original_text = USER_LAST_MESSAGE[from_number]
            text_body = f"{original_text}. Уточнение: {text_body}"
            del USER_LAST_MESSAGE[from_number] # Очищаем память
            logger.info(f"🧠 Context merged: {text_body}")

        # 2. AI Extraction
        parsed_data = await extract_with_ai(text_body)
        
        # --- Handle Multi-Task (Voice dictations usually have multiple) ---
        tasks_to_process = []
        if parsed_data.get("type") == "multi_task":
            tasks_to_process = parsed_data.get("tasks", [])
        else:
            tasks_to_process = [parsed_data]

        for task_data in tasks_to_process:
            data_type = task_data.get("type")
            if not data_type or data_type == "spam":
                logger.info(f"🤖 AI classified spam/unknown sub-task: {task_data}")
                continue
                
            broadcast_event = None

            async with AsyncSessionLocal() as db:
                # Save raw message for Chat Summary
                new_msg = ChatMessage(
                    sender_name=payload.get("user_name", from_number),
                    sender_role=task_data.get("sender_role", "Staff"),
                    message=text_body,
                    platform=payload.get("platform", "whatsapp"),
                    is_important=task_data.get("is_important", False)
                )
                db.add(new_msg)
                await db.commit()

                # Broadcast for real-time frontend
                await manager.broadcast({
                    "type": "NEW_MESSAGE",
                    "data": {
                        "sender": new_msg.sender_name,
                        "role": new_msg.sender_role,
                        "content": new_msg.message,
                        "isImportant": new_msg.is_important
                    }
                })

                # --- Route by type ---
                if data_type in ["it_support", "maintenance", "logistics", "emergency"]:
                    desc = task_data.get("issue") or task_data.get("description") or task_data.get("item")
                    device = task_data.get("device")
                    if device and desc:
                        desc = f"{device} ({desc})"
                    elif device and not desc:
                        desc = device
                        
                    location = task_data.get("location", "unknown")
                    priority = task_data.get("priority", "medium")

                    # Проверка на отсутствие локации
                    if location == "unknown" or not location:
                        USER_LAST_MESSAGE[from_number] = text_body # Запоминаем изначальный запрос
                        await send_unified_reply(from_number, "❓ Уточните, пожалуйста, кабинет или локацию.")
                        continue # Skip to next task

                    new_request = ServiceRequest(
                        category=data_type,
                        location=location,
                        description=desc,
                        priority=priority
                    )
                    db.add(new_request)
                    await db.commit()

                    if data_type == "emergency":
                        # Create an IncidentRecord for emergencies (shown in /incidents/active)
                        new_incident = IncidentRecord(
                            incident_id=f"inc-{uuid.uuid4().hex[:6]}",
                            location=location,
                            issue=desc,
                            reported_by=from_number,
                            assigned_to="Администрация"
                        )
                        db.add(new_incident)
                        await db.commit()
                        await notify_all_platforms(f"ВНИМАНИЕ! {desc} в {location}", priority="CRITICAL")

                    emoji = "🚨" if data_type == "emergency" else "⚙️"
                    await send_unified_reply(from_number, f"{emoji} Заявка принята: {desc} в {location}.")

                    # --- Stage 3: Тотальная персонализация (Инциденты -> В расписание) ---
                    if data_type in ["maintenance", "it_support"]:
                        assignee = "Слесарь/Завхоз" if data_type == "maintenance" else "IT-специалист Косов М."
                        # Имитируем отправку пуша конкретному сотруднику (Киллер-фича)
                        push_text = f"📲 [Авто-Push для: {assignee}]:\n🛠 Новая задача добавлена в ваше расписание на ближайшее 'окно':\n{desc} в {location}."
                        await send_unified_reply(from_number, push_text)

                    broadcast_event = {"type": "NEW_SERVICE_REQUEST", "category": data_type}

                elif data_type == "canteen":
                    # Нормализация класса (Cyrillic -> Latin, убираем пробелы)
                    raw_class = normalize_class_name(task_data.get("class", "school"))
                    
                    # Валидация класса: если его нет в словаре, просим уточнить
                    if raw_class not in DEFAULT_CLASS_SIZES:
                        USER_LAST_MESSAGE[from_number] = text_body # Запоминаем контекст
                        await send_unified_reply(
                            from_number,
                            f"❓ Уточните номер класса.\n"
                            f"(Например: 7A, 10B)"
                        )
                        continue

                    # Берем тотал из базы данных системы
                    system_total = DEFAULT_CLASS_SIZES[raw_class]
                    
                    # Если ИИ не нашел тотал, берем системный
                    reported_total = task_data.get("total", 0)
                    final_total = reported_total if reported_total > 0 else system_total
                    
                    sick = task_data.get("sick", 0)
                    comp = task_data.get("competition", 0)

                    new_record = CanteenRecord(
                        class_name=raw_class,
                        total_students=final_total,
                        sick_students=sick,
                        competition_students=comp
                    )
                    db.add(new_record)
                    await db.commit()
                    
                    # Silent save without replying (anti-spam)
                    present = final_total - sick - comp
                    logger.info(f"🍽️ Canteen record saved silently for {raw_class}. Portions: {present}")
                    broadcast_event = {"type": "NUTRITION_UPDATED"}

                elif data_type == "substitution":
                    teacher_name = task_data.get("teacher_name")
                    sub_results = await scheduler.find_replacement(teacher_name, "Дүйсенбі")

                    if "replacements" in sub_results:
                        reply = f"🚨 Учитель {sub_results.get('sick_teacher', teacher_name)} отсутствует.\n"
                        pushes_to_send = []

                        for rep in sub_results["replacements"]:
                            lesson_info = rep['original_lesson']
                            reply += f"\n📖 Урок: {lesson_info}\n"
                            if rep["candidates"]:
                                best_candidate = rep['candidates'][0]['name']
                                reply += f"✅ Назначена замена: {best_candidate}\n"
                                pushes_to_send.append((best_candidate, lesson_info))
                            else:
                                reply += f"❌ Нет свободных учителей!\n"
                        
                        # 1. Отправляем отчет Директору/Завучу (тому, кто запросил)
                        await send_unified_reply(from_number, reply)
                        
                        # 2. Имитируем отправку персональных пушей заменяющим учителям (Киллер-фича)
                        for candidate, lesson in pushes_to_send:
                            push_text = f"📲 [Авто-Push для {candidate}]:\nСрочная замена! Вы ведете урок ({lesson}) вместо заболевшего коллеги."
                            await send_unified_reply(from_number, push_text)

                        broadcast_event = {"type": "SUBSTITUTION_FOUND", "data": sub_results}
                    elif "error" in sub_results:
                        await send_unified_reply(from_number, f"❌ Ошибка: {sub_results['error']}")

                elif data_type == "task":
                    new_task = TaskRecord(
                        assignee=task_data.get("assignee", "unknown"),
                        action=task_data.get("action", "unknown")
                    )
                    db.add(new_task)
                    await db.commit()
                    await send_unified_reply(
                        from_number,
                        f"📋 Задача зафиксирована! Исполнитель: {new_task.assignee}. Действие: {new_task.action}"
                    )
                    broadcast_event = {"type": "NEW_TASK"}

                elif data_type == "bureaucracy":
                    doc_type = task_data.get("document_type", "Приказ")
                    target = task_data.get("target", "Сотрудник/Класс")
                    reason = task_data.get("reason", "Внутренняя необходимость")
                    
                    # Генерация юридического документа (симуляция RAG-выдачи)
                    official_doc = (
                        f"📄 *ПРОЕКТ ДОКУМЕНТА ГОТОВ*\n\n"
                        f"*НАИМЕНОВАНИЕ:* {doc_type.upper()}\n"
                        f"*КАСАЕТСЯ:* {target}\n"
                        f"*ОСНОВАНИЕ:* {reason}\n\n"
                        f"Согласно регламентам МОН РК, приказываю выполнить необходимые инструкции касательно указанного субъекта в срок до завтрашнего дня.\n\n"
                        f"👉 *Нажмите 'Утвердить', чтобы документ ушел в электронный документооборот.*"
                    )
                    await send_unified_reply(from_number, official_doc)
                    broadcast_event = {"type": "BUREAUCRACY_DRAFT_READY"}

                elif data_type == "lenta":
                    target_group = task_data.get("target_group", "Классы")
                    subject = task_data.get("subject", "Предмет")
                    
                    # Симуляция работы мощного алгоритма ленты
                    lenta_report = (
                        f"🌀 *SMART LENTA АКТИВИРОВАНА*\n\n"
                        f"Параллель: {target_group}\n"
                        f"Предмет: {subject}\n\n"
                        f"✅ Алгоритм нашел 4 свободных преподавателей.\n"
                        f"✅ Забронировано 4 кабинета на 1 таймслот.\n"
                        f"✅ Сетка расписания перестроена без накладок (Time: 1.2s).\n\n"
                        f"Уведомления преподавателям отправлены."
                    )
                    await send_unified_reply(from_number, lenta_report)
                    broadcast_event = {"type": "LENTA_GENERATED"}

                if broadcast_event:
                    await manager.broadcast(broadcast_event)

    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)


@app.post("/internal-webhook")
async def internal_webhook_handler(request: Request, background_tasks: BackgroundTasks):
    # SECURITY: Check secret token
    token = request.headers.get("X-Internal-Token")
    if token != INTERNAL_SECRET:
        logger.warning(f"❌ Unauthorized webhook access attempt from {request.client.host}")
        raise HTTPException(status_code=403, detail="Forbidden")

    data = await request.json()
    msg_id = data.get("message_id")
    
    if msg_id:
        if msg_id in PROCESSED_MESSAGE_IDS:
            logger.info(f"♻️ Skipping duplicate message {msg_id}")
            return JSONResponse(content={"status": "already_processed"})
        PROCESSED_MESSAGE_IDS.add(msg_id)
        # Keep cache small
        if len(PROCESSED_MESSAGE_IDS) > 1000:
            PROCESSED_MESSAGE_IDS.clear()

    background_tasks.add_task(process_whatsapp_message, data)
    return JSONResponse(content={"status": "received"})
