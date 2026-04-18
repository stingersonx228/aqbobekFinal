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

load_dotenv()

from src.database import engine, Base, get_db, AsyncSessionLocal
from src.models import IncidentRecord, CanteenRecord, TaskRecord
from src.schemas import NutritionReportResponse, AbsentDetails, IncidentsResponse, IncidentDetail, TasksResponse, TaskDetail
from src.ai_service import extract_with_gemini
from src.whatsapp_service import send_whatsapp_message
from src.export_service import generate_excel_report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Aqbobek WhatsApp Server")

# --- CORS Configuration for Frontend Integration ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all for hackathon
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

@app.get("/")
def read_root():
    return {"status": "Aqbobek WhatsApp Python Backend is running"}

# --- WebSocket Endpoint ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text() # Keep connection alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# --- REST API Endpoints for Frontend Dashboard ---

@app.get("/api/v1/nutrition/today", response_model=NutritionReportResponse)
async def get_nutrition_today(db: AsyncSession = Depends(get_db)):
    """API endpoint for Frontend Dashboard to get today's attendance stats"""
    # In a real app, filter by today's date using SQLAlchemy.
    # For hackathon simplicity, we aggregate all records.
    result = await db.execute(select(
        func.sum(CanteenRecord.sick_students).label('total_sick'),
        func.sum(CanteenRecord.competition_students).label('total_comp'),
        func.count(CanteenRecord.id).label('messages_count')
    ))
    row = result.fetchone()
    
    sick = row.total_sick or 0
    comp = row.total_comp or 0
    parsed_msgs = row.messages_count or 0

    return NutritionReportResponse(
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        totalVseobuch=400, # Mock total students
        absentDetails=AbsentDetails(sick_count=sick, competition_count=comp),
        rawMessagesParsed=parsed_msgs,
        status="success"
    )

@app.get("/api/v1/incidents/active", response_model=IncidentsResponse)
async def get_active_incidents(db: AsyncSession = Depends(get_db)):
    """API endpoint for Frontend Dashboard to get open incidents"""
    result = await db.execute(select(IncidentRecord).where(IncidentRecord.status == "open"))
    incidents = result.scalars().all()
    
    return IncidentsResponse(
        incidents=[
            IncidentDetail(
                id=inc.incident_id or f"inc-{inc.id}",
                timestamp=inc.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if inc.created_at else "",
                location=inc.location,
                description=inc.issue,
                reporter=inc.reported_by or "Неизвестный",
                assignedTo=inc.assigned_to or "Завхоз",
                status=inc.status
            ) for inc in incidents
        ]
    )

@app.get("/api/v1/tasks/active", response_model=TasksResponse)
async def get_active_tasks(db: AsyncSession = Depends(get_db)):
    """Bonus endpoint for Tasks"""
    result = await db.execute(select(TaskRecord).where(TaskRecord.status == "pending"))
    tasks = result.scalars().all()
    
    return TasksResponse(
        tasks=[
            TaskDetail(
                id=t.id,
                assignee=t.assignee,
                action=t.action,
                status=t.status,
                timestamp=t.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if t.created_at else ""
            ) for t in tasks
        ]
    )


# --- WhatsApp Webhook Processing ---

async def process_whatsapp_message(message_data: dict):
    """Background task to process the message from Node.js Bridge"""
    try:
        from src.database import AsyncSessionLocal
        
        from_number = message_data.get("from")
        text_body = message_data.get("body", "")
        
        if not text_body:
            return

        logger.info(f"Received message from {from_number}: {text_body}")

        # Check for commands
        if text_body.strip().lower() == "/report":
            await send_whatsapp_message(from_number, "Generating report, please wait...")
            async with AsyncSessionLocal() as db:
                filepath = await generate_excel_report(db)
            
            await send_whatsapp_message(from_number, f"Report generated successfully on server. Path: {filepath}")
            return

        # 1. AI Extraction
        parsed_data = await extract_with_gemini(text_body)
        data_type = parsed_data.get("type")
        
        reply_text = "I couldn't understand that. Please report canteen attendance, incidents, or tasks."
        broadcast_event = None

        # 2. Database Save & Format Reply
        async with AsyncSessionLocal() as db:
            if data_type == "incident":
                new_incident = IncidentRecord(
                    incident_id=f"inc-{uuid.uuid4().hex[:6]}",
                    location=parsed_data.get("location", "unknown"),
                    issue=parsed_data.get("issue", "unknown"),
                    reported_by=parsed_data.get("reporter", from_number),
                    assigned_to=parsed_data.get("assignedTo", "Завхоз")
                )
                db.add(new_incident)
                await db.commit()
                reply_text = f"Зафиксирован инцидент:\nЛокация: {new_incident.location}\nПроблема: {new_incident.issue}\nОтправлено завхозу."
                broadcast_event = {"type": "NEW_INCIDENT"}
                
                # ОТВЕЧАЕМ ТОЛЬКО НА ИНЦИДЕНТЫ
                await send_whatsapp_message(from_number, reply_text)
                
            elif data_type == "canteen":
                new_record = CanteenRecord(
                    class_name=parsed_data.get("class", "school"),
                    total_students=parsed_data.get("total", 0),
                    sick_students=parsed_data.get("sick", 0),
                    competition_students=parsed_data.get("competition", 0)
                )
                db.add(new_record)
                await db.commit()
                # reply_text = f"[CANTEEN SAVED] {new_record.sick_students} sick, {new_record.competition_students} on competition."
                broadcast_event = {"type": "NUTRITION_UPDATED"}
                
            elif data_type == "task":
                new_task = TaskRecord(
                    assignee=parsed_data.get("assignee", "unknown"),
                    action=parsed_data.get("action", "unknown")
                )
                db.add(new_task)
                await db.commit()
                # reply_text = f"[TASK CREATED] For: {new_task.assignee}"
                broadcast_event = {"type": "NEW_TASK"}

        # 4. WebSockets: Broadcast event to frontend dashboard so they refresh data!
        if broadcast_event:
            await manager.broadcast(broadcast_event)

    except Exception as e:
        logger.error(f"Error processing message: {e}")

@app.post("/internal-webhook")
async def internal_webhook_handler(request: Request, background_tasks: BackgroundTasks):
    """Receive messages from our local Node.js whatsapp-web.js bridge"""
    data = await request.json()
    
    try:
        background_tasks.add_task(process_whatsapp_message, data)
        return JSONResponse(content={"status": "received"}, status_code=200)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return JSONResponse(content={"status": "error"}, status_code=500)
