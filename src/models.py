from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
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

class ServiceRequest(Base):
    """Unified table for IT, Logistics, Emergency and Maintenance"""
    __tablename__ = "service_requests"
    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, index=True) # it_support, logistics, emergency, maintenance
    location = Column(String, index=True)
    description = Column(String)
    priority = Column(String, default="medium")
    status = Column(String, default="open")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class ChatMessage(Base):
    """Table for the 'Chat Summary' section on the dashboard"""
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, index=True)
    sender_name = Column(String)
    sender_role = Column(String) # AI determined
    message = Column(String)
    platform = Column(String) # telegram / whatsapp
    is_important = Column(Boolean, default=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

# --- NEW ERP TABLES ---

class Teacher(Base):
    __tablename__ = "teachers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    role = Column(String) # e.g. "Teacher", "IT", "Janitor"
    loads = relationship("TeacherLoad", back_populates="teacher")
    schedule_entries = relationship("ScheduleEntry", back_populates="teacher")

class Subject(Base):
    __tablename__ = "subjects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, unique=True)
    loads = relationship("TeacherLoad", back_populates="subject")
    schedule_entries = relationship("ScheduleEntry", back_populates="subject")

class SchoolClass(Base):
    __tablename__ = "classes"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, unique=True) # e.g. "7A"
    grade = Column(Integer)
    student_count = Column(Integer, default=0)
    loads = relationship("TeacherLoad", back_populates="school_class")
    schedule_entries = relationship("ScheduleEntry", back_populates="school_class")

class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True, index=True)
    number = Column(String, index=True)
    floor = Column(Integer)
    capacity = Column(Integer)
    description = Column(String)

class TeacherLoad(Base):
    """How many hours a teacher teaches a subject to a class"""
    __tablename__ = "teacher_loads"
    id = Column(Integer, primary_key=True, index=True)
    teacher_id = Column(Integer, ForeignKey("teachers.id"))
    subject_id = Column(Integer, ForeignKey("subjects.id"))
    class_id = Column(Integer, ForeignKey("classes.id"))
    hours_per_week = Column(Float)

    teacher = relationship("Teacher", back_populates="loads")
    subject = relationship("Subject", back_populates="loads")
    school_class = relationship("SchoolClass", back_populates="loads")

class TimeSlot(Base):
    __tablename__ = "time_slots"
    id = Column(Integer, primary_key=True, index=True)
    lesson_number = Column(Integer)
    start_time = Column(String)
    end_time = Column(String)
    slot_type = Column(String, default="lesson") # lesson, break, meal

class ScheduleEntry(Base):
    __tablename__ = "schedule"
    id = Column(Integer, primary_key=True, index=True)
    day_of_week = Column(String)
    slot_id = Column(Integer, ForeignKey("time_slots.id"))
    class_id = Column(Integer, ForeignKey("classes.id"))
    teacher_id = Column(Integer, ForeignKey("teachers.id"))
    subject_id = Column(Integer, ForeignKey("subjects.id"))
    room_id = Column(Integer, ForeignKey("rooms.id"))

    time_slot = relationship("TimeSlot")
    school_class = relationship("SchoolClass", back_populates="schedule_entries")
    teacher = relationship("Teacher", back_populates="schedule_entries")
    subject = relationship("Subject", back_populates="schedule_entries")
    room = relationship("Room")
