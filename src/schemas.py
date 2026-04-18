from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# --- Incoming Extraction Models ---

class WebhookChallenge(BaseModel):
    hub_mode: str
    hub_challenge: int
    hub_verify_token: str

class CanteenCreate(BaseModel):
    class_name: str
    total_students: int
    sick_students: int
    competition_students: int = 0

class IncidentCreate(BaseModel):
    location: str
    issue: str
    reported_by: Optional[str] = None
    assigned_to: str = "Завхоз"

class TaskCreate(BaseModel):
    assignee: str
    action: str

# --- Outgoing API Response Models (For Frontend) ---

class AbsentDetails(BaseModel):
    sick_count: int
    competition_count: int

class NutritionReportResponse(BaseModel):
    date: str
    totalVseobuch: int
    absentDetails: AbsentDetails
    rawMessagesParsed: int
    status: str

class IncidentDetail(BaseModel):
    id: str
    timestamp: str
    location: str
    description: str
    reporter: str
    assignedTo: str
    status: str

class IncidentsResponse(BaseModel):
    incidents: List[IncidentDetail]

class TaskDetail(BaseModel):
    id: int
    assignee: str
    action: str
    status: str
    timestamp: str

class TasksResponse(BaseModel):
    tasks: List[TaskDetail]
