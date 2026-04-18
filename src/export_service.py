import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from .models import IncidentRecord, CanteenRecord, TaskRecord
import os

async def generate_excel_report(db: AsyncSession, filepath: str = "./report.xlsx") -> str:
    """Fetches data from database and generates an Excel report."""
    
    # Fetch Incidents
    result_incidents = await db.execute(select(IncidentRecord))
    incidents = result_incidents.scalars().all()
    incidents_data = [{
        "System ID": i.id, "Incident ID": i.incident_id, "Location": i.location, "Issue": i.issue, 
        "Status": i.status, "Reported By": i.reported_by, "Assigned To": i.assigned_to, "Date": i.created_at.strftime("%Y-%m-%d %H:%M:%S") if i.created_at else ""
    } for i in incidents]
    
    # Fetch Canteen
    result_canteen = await db.execute(select(CanteenRecord))
    canteen = result_canteen.scalars().all()
    canteen_data = [{
        "ID": c.id, "Class": c.class_name, "Total": c.total_students, 
        "Sick": c.sick_students, "On Competition": c.competition_students, "Date": c.created_at.strftime("%Y-%m-%d %H:%M:%S") if c.created_at else ""
    } for c in canteen]

    # Fetch Tasks
    result_tasks = await db.execute(select(TaskRecord))
    tasks = result_tasks.scalars().all()
    tasks_data = [{
        "ID": t.id, "Assignee": t.assignee, "Action": t.action, 
        "Status": t.status, "Date": t.created_at.strftime("%Y-%m-%d %H:%M:%S") if t.created_at else ""
    } for t in tasks]

    # Write to Excel
    with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
        df_incidents = pd.DataFrame(incidents_data) if incidents_data else pd.DataFrame(columns=["System ID", "Incident ID", "Location", "Issue", "Status", "Reported By", "Assigned To", "Date"])
        df_canteen = pd.DataFrame(canteen_data) if canteen_data else pd.DataFrame(columns=["ID", "Class", "Total", "Sick", "On Competition", "Date"])
        df_tasks = pd.DataFrame(tasks_data) if tasks_data else pd.DataFrame(columns=["ID", "Assignee", "Action", "Status", "Date"])
        
        df_incidents.to_excel(writer, sheet_name='Incidents', index=False)
        df_canteen.to_excel(writer, sheet_name='Canteen', index=False)
        df_tasks.to_excel(writer, sheet_name='Tasks', index=False)
        
    return filepath
