from typing import List, Optional, Dict
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload
from .database import AsyncSessionLocal
from .models import Teacher, TeacherLoad, SchoolClass, ScheduleEntry, TimeSlot, Subject, Room

class SchedulerService:
    def __init__(self):
        pass

    async def get_teacher_by_name(self, name: str):
        async with AsyncSessionLocal() as session:
            # 1. Try exact ilike
            stmt = select(Teacher).filter(Teacher.name.ilike(f"%{name}%"))
            result = await session.execute(stmt)
            teacher = result.scalars().first()
            if teacher: return teacher

            # 2. Try surname fuzzy (first word)
            surname = name.split()[0].replace(".", "").strip()
            stmt = select(Teacher).filter(Teacher.name.ilike(f"{surname}%"))
            result = await session.execute(stmt)
            return result.scalars().first()

    async def get_personal_schedule(self, person_name: str, day: str) -> List[Dict]:
        """
        Relational search for schedule entries.
        """
        async with AsyncSessionLocal() as session:
            teacher = await self.get_teacher_by_name(person_name)
            if not teacher:
                return []

            stmt = (
                select(ScheduleEntry)
                .options(selectinload(ScheduleEntry.subject), selectinload(ScheduleEntry.room), selectinload(ScheduleEntry.time_slot))
                .filter(and_(ScheduleEntry.teacher_id == teacher.id, ScheduleEntry.day_of_week == day))
            )
            result = await session.execute(stmt)
            entries = result.scalars().all()
            
            return [
                {
                    "time": f"{e.time_slot.start_time}-{e.time_slot.end_time}",
                    "subject": e.subject.name,
                    "room": e.room.number,
                    "lesson": e.time_slot.lesson_number
                }
                for e in entries
            ]

    async def find_replacement(self, sick_teacher_name: str, day: str, time_slot: Optional[str] = None):
        """
        SQL replacement engine:
        1. Find what subject and classes the teacher has.
        2. Find teachers who teach the same subject (competency).
        3. Verify their availability in the schedule table.
        """
        async with AsyncSessionLocal() as session:
            sick_teacher = await self.get_teacher_by_name(sick_teacher_name)
            if not sick_teacher:
                return {"error": f"Teacher '{sick_teacher_name}' not found."}

            # Find lessons for this teacher
            stmt = (
                select(ScheduleEntry)
                .options(selectinload(ScheduleEntry.subject), selectinload(ScheduleEntry.room), selectinload(ScheduleEntry.time_slot), selectinload(ScheduleEntry.school_class))
                .filter(and_(ScheduleEntry.teacher_id == sick_teacher.id, ScheduleEntry.day_of_week == day))
            )
            result = await session.execute(stmt)
            sick_lessons = result.scalars().all()

            if not sick_lessons:
                return {"message": f"Teacher {sick_teacher.name} has no lessons on {day}."}

            final_replacements = []
            for lesson in sick_lessons:
                subject_id = lesson.subject_id
                slot_id = lesson.slot_id
                
                # 1. Find candidates with same subject expertise
                candidate_stmt = (
                    select(Teacher)
                    .join(TeacherLoad)
                    .filter(and_(TeacherLoad.subject_id == subject_id, Teacher.id != sick_teacher.id))
                    .distinct()
                )
                cand_result = await session.execute(candidate_stmt)
                candidates = cand_result.scalars().all()

                available_candidates = []
                for cand in candidates:
                    # Check if free at this time
                    busy_stmt = select(ScheduleEntry).filter(and_(
                        ScheduleEntry.teacher_id == cand.id,
                        ScheduleEntry.day_of_week == day,
                        ScheduleEntry.slot_id == slot_id
                    ))
                    is_busy = (await session.execute(busy_stmt)).scalars().first()
                    
                    if not is_busy:
                        available_candidates.append({"id": cand.id, "name": cand.name, "reason": "Subject Expert"})

                # 2. If no experts, find any free teacher
                if not available_candidates:
                    free_stmt = select(Teacher).filter(Teacher.id != sick_teacher.id).limit(20)
                    all_teachers = (await session.execute(free_stmt)).scalars().all()
                    for t in all_teachers:
                        busy_stmt = select(ScheduleEntry).filter(and_(
                            ScheduleEntry.teacher_id == t.id,
                            ScheduleEntry.day_of_week == day,
                            ScheduleEntry.slot_id == slot_id
                        ))
                        is_busy = (await session.execute(busy_stmt)).scalars().first()
                        if not is_busy:
                            available_candidates.append({"id": t.id, "name": t.name, "reason": "Free during slot"})
                            if len(available_candidates) >= 2: break

                final_replacements.append({
                    "original_lesson": f"{lesson.subject.name} in {lesson.room.number} for {lesson.school_class.name}",
                    "time": f"{lesson.time_slot.start_time}",
                    "candidates": available_candidates[:3]
                })

            return {
                "sick_teacher": sick_teacher.name,
                "day": day,
                "replacements": final_replacements
            }

    async def find_free_teachers(self, day: str, time_slot: str) -> List[Dict]:
        """
        Find teachers who are NOT in the schedule for a specific day and time slot.
        """
        async with AsyncSessionLocal() as session:
            # 1. Find the time slot
            slot_stmt = select(TimeSlot).filter(TimeSlot.start_time.ilike(f"%{time_slot.split('-')[0]}%"))
            slot = (await session.execute(slot_stmt)).scalars().first()
            if not slot:
                return []

            # 2. Find busy teachers
            busy_stmt = select(ScheduleEntry.teacher_id).filter(and_(
                ScheduleEntry.day_of_week == day,
                ScheduleEntry.slot_id == slot.id
            ))
            busy_ids = (await session.execute(busy_stmt)).scalars().all()

            # 3. Find free teachers
            free_stmt = select(Teacher).filter(~Teacher.id.in_(busy_ids))
            result = await session.execute(free_stmt)
            free_teachers = result.scalars().all()

            return [{"name": t.name} for t in free_teachers]

# Global instance
scheduler = SchedulerService()
