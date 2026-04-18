"""
Aqbobek Report Engine
---------------------
Generates daily summaries for the canteen, incidents, tasks and service requests.
Supports: Excel export, JSON summary, and scheduled auto-reports.
"""

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, cast, Date
from datetime import datetime, timezone, timedelta

ALMATY_TZ = timezone(timedelta(hours=5))  # UTC+5 Алматы
from .models import IncidentRecord, CanteenRecord, TaskRecord, ServiceRequest, ChatMessage, SchoolClass, Teacher, Subject, TeacherLoad
import logging
import json
import os

logger = logging.getLogger(__name__)

async def get_total_students_count(db: AsyncSession) -> int:
    """Dynamically get total students from the database classes table."""
    result = await db.execute(select(func.sum(SchoolClass.student_count)))
    count = result.scalar()
    return count if count and count > 0 else 400 # Fallback to 400 if DB is empty


async def get_canteen_summary(db: AsyncSession, date: datetime = None) -> dict:
    """
    KILLER FEATURE: Daily canteen summary.
    This is exactly what the ТЗ asks for — aggregate all teacher messages
    and produce a single report: "Total: 380 portions. Absent: 20."
    """
    if date is None:
        date = datetime.now(ALMATY_TZ)

    # Get today's records
    today_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    result = await db.execute(
        select(
            func.sum(CanteenRecord.total_students).label('total_reported'),
            func.sum(CanteenRecord.sick_students).label('total_sick'),
            func.sum(CanteenRecord.competition_students).label('total_competition'),
            func.count(CanteenRecord.id).label('messages_parsed')
        ).where(
            CanteenRecord.created_at >= today_start,
            CanteenRecord.created_at < today_end
        )
    )
    row = result.fetchone()

    total_reported = row.total_reported or 0
    total_sick = row.total_sick or 0
    total_competition = row.total_competition or 0
    messages_parsed = row.messages_parsed or 0
    
    # DYNAMIC TOTAL
    total_school_students = await get_total_students_count(db)

    total_absent = total_sick + total_competition
    total_present = total_school_students - total_absent
    portions_needed = total_present

    # Per-class breakdown
    classes_result = await db.execute(
        select(CanteenRecord).where(
            CanteenRecord.created_at >= today_start,
            CanteenRecord.created_at < today_end
        ).order_by(CanteenRecord.class_name)
    )
    classes = classes_result.scalars().all()

    breakdown = []
    for c in classes:
        breakdown.append({
            "class": c.class_name,
            "total": c.total_students,
            "sick": c.sick_students,
            "competition": c.competition_students,
            "present": c.total_students - c.sick_students - c.competition_students
        })

    return {
        "date": date.strftime("%Y-%m-%d"),
        "school_total": total_school_students,
        "total_present": total_present,
        "total_absent": total_absent,
        "absent_sick": total_sick,
        "absent_competition": total_competition,
        "portions_needed": portions_needed,
        "messages_parsed": messages_parsed,
        "class_breakdown": breakdown,
        # Ready-made text for the cafeteria manager
        "cafeteria_text": (
            f"📋 СВОД ПО СТОЛОВОЙ на {date.strftime('%d.%m.%Y')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👨‍🎓 Всего учеников (по базе): {total_school_students}\n"
            f"✅ Присутствуют: {total_present}\n"
            f"🤒 Болеют: {total_sick}\n"
            f"🏆 На соревнованиях: {total_competition}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🍽 ПОРЦИЙ К ВЫДАЧЕ: {portions_needed}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📨 Обработано сообщений: {messages_parsed}"
        )
    }


async def get_daily_stats(db: AsyncSession, date: datetime = None) -> dict:
    """Full daily statistics for the director's dashboard."""
    if date is None:
        date = datetime.now(ALMATY_TZ)

    today_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    # Canteen summary
    canteen = await get_canteen_summary(db, date)

    # Incidents today
    incidents_result = await db.execute(
        select(func.count(IncidentRecord.id)).where(
            IncidentRecord.created_at >= today_start,
            IncidentRecord.created_at < today_end
        )
    )
    incidents_count = incidents_result.scalar() or 0

    open_incidents = await db.execute(
        select(func.count(IncidentRecord.id)).where(
            IncidentRecord.status == "open"
        )
    )
    open_incidents_count = open_incidents.scalar() or 0

    # Tasks today
    tasks_result = await db.execute(
        select(func.count(TaskRecord.id)).where(
            TaskRecord.created_at >= today_start,
            TaskRecord.created_at < today_end
        )
    )
    tasks_count = tasks_result.scalar() or 0

    pending_tasks = await db.execute(
        select(func.count(TaskRecord.id)).where(
            TaskRecord.status == "pending"
        )
    )
    pending_tasks_count = pending_tasks.scalar() or 0

    # Service Requests today
    service_result = await db.execute(
        select(ServiceRequest.category, func.count(ServiceRequest.id)).where(
            ServiceRequest.created_at >= today_start,
            ServiceRequest.created_at < today_end
        ).group_by(ServiceRequest.category)
    )
    service_by_category = {row[0]: row[1] for row in service_result.fetchall()}

    # Messages today
    messages_result = await db.execute(
        select(func.count(ChatMessage.id)).where(
            ChatMessage.timestamp >= today_start,
            ChatMessage.timestamp < today_end
        )
    )
    messages_count = messages_result.scalar() or 0

    return {
        "date": date.strftime("%Y-%m-%d"),
        "canteen": canteen,
        "incidents": {
            "today": incidents_count,
            "open_total": open_incidents_count
        },
        "tasks": {
            "today": tasks_count,
            "pending_total": pending_tasks_count
        },
        "service_requests": service_by_category,
        "messages_total": messages_count
    }


async def generate_excel_report(db: AsyncSession, filepath: str = "./report.xlsx") -> str:
    """Generates a comprehensive Excel report with multiple sheets."""

    # --- Canteen ---
    result_canteen = await db.execute(select(CanteenRecord).order_by(CanteenRecord.created_at.desc()))
    canteen = result_canteen.scalars().all()
    canteen_data = [{
        "Класс": c.class_name,
        "Всего": c.total_students,
        "Болеют": c.sick_students,
        "На соревнованиях": c.competition_students,
        "Присутствуют": c.total_students - c.sick_students - c.competition_students,
        "Дата": c.created_at.strftime("%d.%m.%Y %H:%M") if c.created_at else ""
    } for c in canteen]

    # --- Incidents ---
    result_incidents = await db.execute(select(IncidentRecord).order_by(IncidentRecord.created_at.desc()))
    incidents = result_incidents.scalars().all()
    incidents_data = [{
        "ID": i.incident_id,
        "Локация": i.location,
        "Проблема": i.issue,
        "Статус": i.status,
        "Заявитель": i.reported_by,
        "Исполнитель": i.assigned_to,
        "Дата": i.created_at.strftime("%d.%m.%Y %H:%M") if i.created_at else ""
    } for i in incidents]

    # --- Tasks ---
    result_tasks = await db.execute(select(TaskRecord).order_by(TaskRecord.created_at.desc()))
    tasks = result_tasks.scalars().all()
    tasks_data = [{
        "Исполнитель": t.assignee,
        "Задача": t.action,
        "Статус": t.status,
        "Дата": t.created_at.strftime("%d.%m.%Y %H:%M") if t.created_at else ""
    } for t in tasks]

    # --- Service Requests ---
    result_service = await db.execute(select(ServiceRequest).order_by(ServiceRequest.created_at.desc()))
    services = result_service.scalars().all()
    service_data = [{
        "Категория": s.category,
        "Локация": s.location,
        "Описание": s.description,
        "Приоритет": s.priority,
        "Статус": s.status,
        "Дата": s.created_at.strftime("%d.%m.%Y %H:%M") if s.created_at else ""
    } for s in services]

    # --- ERP Data (Teachers & Loads) ---
    from sqlalchemy.orm import selectinload
    result_loads = await db.execute(select(TeacherLoad).options(selectinload(TeacherLoad.teacher), selectinload(TeacherLoad.subject), selectinload(TeacherLoad.school_class)))
    loads = result_loads.scalars().all()
    loads_data = [{
        "Учитель": l.teacher.name,
        "Предмет": l.subject.name,
        "Класс": l.school_class.name,
        "Часов в неделю": l.hours_per_week
    } for l in loads]

    # --- Write Excel ---
    with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
        # Summary sheet
        summary = await get_canteen_summary(db)
        summary_df = pd.DataFrame([{
            "Дата": summary["date"],
            "Всего учеников": summary["school_total"],
            "Присутствуют": summary["total_present"],
            "Отсутствуют": summary["total_absent"],
            "Болеют": summary["absent_sick"],
            "На соревнованиях": summary["absent_competition"],
            "Порций к выдаче": summary["portions_needed"]
        }])
        summary_df.to_excel(writer, sheet_name='Свод на сегодня', index=False)

        # Detail sheets
        df_canteen = pd.DataFrame(canteen_data) if canteen_data else pd.DataFrame(columns=["Класс", "Всего", "Болеют", "На соревнованиях", "Присутствуют", "Дата"])
        df_incidents = pd.DataFrame(incidents_data) if incidents_data else pd.DataFrame(columns=["ID", "Локация", "Проблема", "Статус", "Заявитель", "Исполнитель", "Дата"])
        df_tasks = pd.DataFrame(tasks_data) if tasks_data else pd.DataFrame(columns=["Исполнитель", "Задача", "Статус", "Дата"])
        df_service = pd.DataFrame(service_data) if service_data else pd.DataFrame(columns=["Категория", "Локация", "Описание", "Приоритет", "Статус", "Дата"])

        df_canteen.to_excel(writer, sheet_name='Столовая', index=False)
        df_incidents.to_excel(writer, sheet_name='Инциденты', index=False)
        df_tasks.to_excel(writer, sheet_name='Задачи', index=False)
        df_service.to_excel(writer, sheet_name='Заявки', index=False)
        
        # New ERP Sheets
        if loads_data:
            pd.DataFrame(loads_data).to_excel(writer, sheet_name='Нагрузка учителей', index=False)

    logger.info(f"📊 Excel report generated: {filepath}")
    return filepath
