from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.sql import func
from .database import Base

class CanteenRecord(Base):
    __tablename__ = "canteen_records"
    id = Column(Integer, primary_key=True, index=True)
    class_name = Column(String, index=True)
    total_students = Column(Integer, default=0)
    sick_students = Column(Integer, default=0)
    competition_students = Column(Integer, default=0) # NEW
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class IncidentRecord(Base):
    __tablename__ = "incidents"
    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(String, unique=True, index=True) # NEW (e.g. inc-001)
    location = Column(String, index=True)
    issue = Column(String)
    status = Column(String, default="open") # open, resolved
    reported_by = Column(String) # WhatsApp number or extracted Name
    assigned_to = Column(String, default="Завхоз") # NEW
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class TaskRecord(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    assignee = Column(String, index=True)
    action = Column(String)
    status = Column(String, default="pending") # pending, done
    created_at = Column(DateTime(timezone=True), server_default=func.now())
