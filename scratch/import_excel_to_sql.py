import pandas as pd
import glob
import os
import re
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
import sys

# Add current directory to path so we can import src
sys.path.append(os.getcwd())

from src.models import Base, Teacher, Subject, SchoolClass, Room, TeacherLoad, TimeSlot, ScheduleEntry

# SQLite URL (sync version for ETL)
DATABASE_URL_SYNC = "sqlite:///./aqbobek.db"
engine = create_engine(DATABASE_URL_SYNC)
Session = sessionmaker(bind=engine)
session = Session()

def init_db():
    Base.metadata.drop_all(engine) # Start fresh to avoid duplicates from previous runs
    Base.metadata.create_all(engine)
    print("Database tables created.")

def normalize_name(name):
    if pd.isna(name): return None
    # Strip, normalize spaces, lowercase for matching
    name = str(name).strip().rstrip('/')
    # Standardize common variations
    name = name.replace(" ", "") # Remove spaces for lookup comparison
    return name

def get_or_create_subject(session, raw_name):
    if pd.isna(raw_name): return None
    clean_name = str(raw_name).strip().rstrip('/')
    norm_search = clean_name.replace(" ", "").lower()
    
    all_subjects = session.query(Subject).all()
    for sub in all_subjects:
        if sub.name.replace(" ", "").lower() == norm_search:
            return sub
            
    new_sub = Subject(name=clean_name)
    session.add(new_sub)
    session.flush()
    return new_sub

def get_or_create_teacher(session, raw_name):
    if pd.isna(raw_name): return None
    clean_name = str(raw_name).strip()
    surname = clean_name.split()[0].lower()
    
    all_teachers = session.query(Teacher).all()
    for t in all_teachers:
        if t.name.lower().startswith(surname):
            return t
            
    t = Teacher(name=clean_name, role="Teacher")
    session.add(t)
    session.flush()
    return t

def import_data():
    files = glob.glob("*.xlsx")
    target = None
    for f in files:
        if "2025-2026" in f:
            target = f
            break
    
    if not target:
        print("Excel not found")
        return

    xl = pd.ExcelFile(target)
    
    # 1. Import Rooms
    print("Importing Rooms...")
    rooms_df = pd.read_excel(target, sheet_name='Кабинеттер тізімі')
    for _, row in rooms_df.iterrows():
        if pd.isna(row['Кабинет']): continue
        room = Room(
            number=str(row['Кабинет']),
            floor=int(row['Қабат']) if not pd.isna(row['Қабат']) else None,
            capacity=int(row['Орын саны']) if not pd.isna(row['Орын саны']) else None,
            description=normalize_name(row['Сипаттама'])
        )
        session.add(room)
    session.commit()

    # 2. Import Time Slots
    print("Importing Time Slots...")
    time_df = pd.read_excel(target, sheet_name='Күн тәртібі')
    for _, row in time_df.iterrows():
        l_num = row['Сабақ']
        time_range = row['Уақыт/шара']
        if pd.isna(time_range): continue
        
        slot_type = "lesson" if not pd.isna(l_num) else "other"
        if "ас" in str(time_range).lower(): slot_type = "meal"
        
        start_time, end_time = None, None
        times = re.findall(r'\d{1,2}[\.:]\d{2}', str(time_range))
        if len(times) >= 2:
            start_time, end_time = times[0], times[1]
            
        slot = TimeSlot(
            lesson_number=int(l_num) if not pd.isna(l_num) else None,
            start_time=start_time,
            end_time=end_time,
            slot_type=slot_type
        )
        session.add(slot)
    session.commit()

    # 3. Import Teacher Load (Complex Sheet)
    print("Importing Teachers and Loads...")
    load_df = pd.read_excel(target, sheet_name='Жүктеме 2025-2026', header=None)
    
    # Row 0 is header with class names
    class_headers = load_df.iloc[0].values
    # Row 1 is student counts
    student_counts = load_df.iloc[1].values
    
    # Class columns are roughly 4 to 12 (7A-9B) and 14 to 17 (10A-11B)
    class_cols = {}
    for i, name in enumerate(class_headers):
        if isinstance(name, str) and re.match(r'\d{1,2}[A-ZА-Я]', name):
            class_cols[i] = name
            # Create class if not exists
            if not session.query(SchoolClass).filter_by(name=name).first():
                count = int(student_counts[i]) if not pd.isna(student_counts[i]) else 0
                grade = int(re.search(r'\d+', name).group())
                sc = SchoolClass(name=name, grade=grade, student_count=count)
                session.add(sc)
    session.commit()

    current_teacher = None
    for i in range(2, len(load_df)):
        row = load_df.iloc[i]
        
        teacher_name = normalize_name(row[1])
        if teacher_name and not pd.isna(row[0]): # row[0] is index №
            current_teacher = get_or_create_teacher(session, teacher_name)
        
        subject_name = normalize_name(row[3])
        if subject_name and current_teacher:
            subject = get_or_create_subject(session, subject_name)
            
            # Check hours for each class
            for col_idx, class_name in class_cols.items():
                hours = row[col_idx]
                if not pd.isna(hours) and isinstance(hours, (int, float)) and hours > 0:
                    cls = session.query(SchoolClass).filter_by(name=class_name).first()
                    load = TeacherLoad(
                        teacher_id=current_teacher.id,
                        subject_id=subject.id,
                        class_id=cls.id,
                        hours_per_week=float(hours)
                    )
                    session.add(load)
    
    session.commit()
    
    # 4. Import Initial Timetable from JSON (Seed data)
    print("Seeding Initial Timetable from schedule.json...")
    import json as json_lib
    if os.path.exists("data/schedule.json"):
        with open("data/schedule.json", "r", encoding="utf-8") as f:
            js_data = json_lib.load(f)
            
        for day, lessons in js_data.get("schedule", {}).items():
            for l in lessons:
                # Find or Create TimeSlot
                l_num = l.get("lesson")
                t_range = l.get("time")
                start_t = t_range.split("-")[0] if t_range else None
                
                slot = session.query(TimeSlot).filter_by(lesson_number=l_num, start_time=start_t).first()
                if not slot:
                    slot = TimeSlot(lesson_number=l_num, start_time=start_t, slot_type="lesson")
                    session.add(slot)
                    session.flush()

                # Find Teacher by ID or Name
                t_id_js = l.get("teacher") # e.g. T01
                t_obj = None
                if t_id_js.startswith("T"):
                    # Match by name from the json's teacher list
                    for t_info in js_data.get("teachers", []):
                        if t_info["id"] == t_id_js:
                            t_obj = get_or_create_teacher(session, t_info['name'])
                            break
                
                # Find Subject
                sub_name = l.get("subject")
                sub = get_or_create_subject(session, sub_name)

                # Find Room
                r_num = str(l.get("room"))
                rm = session.query(Room).filter_by(number=r_num).first()
                if not rm:
                    rm = Room(number=r_num)
                    session.add(rm)
                    session.flush()

                # Class (Defaulting if not specified in JSON)
                cls_name = l.get("parallel", "10A") # fallback
                cls = session.query(SchoolClass).filter_by(name=cls_name).first()
                if not cls:
                    cls = SchoolClass(name=cls_name)
                    session.add(cls)
                    session.flush()

                entry = ScheduleEntry(
                    day_of_week=day,
                    slot_id=slot.id,
                    class_id=cls.id,
                    teacher_id=t_obj.id if t_obj else None,
                    subject_id=sub.id,
                    room_id=rm.id
                )
                session.add(entry)
        session.commit()
    
    print("Import completed successfully.")

if __name__ == "__main__":
    init_db()
    import_data()
