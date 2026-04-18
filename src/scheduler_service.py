import json
import os
from typing import List, Optional, Dict

class SchedulerService:
    def __init__(self, data_path: str = "data/schedule.json"):
        self.data_path = data_path
        self.data = self._load_data()

    def _load_data(self):
        if not os.path.exists(self.data_path):
            return {"teachers": [], "schedule": {}}
        with open(self.data_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def find_replacement(self, sick_teacher_name: str, day: str, time_slot: Optional[str] = None):
        """
        Find a replacement for a sick teacher.
        If time_slot is None, find replacements for all lessons of the day.
        """
        teachers = self.data.get("teachers", [])
        schedule = self.data.get("schedule", {}).get(day, [])
        
        # 1. Find teacher ID
        sick_teacher_id = None
        sick_teacher_obj = None
        for t in teachers:
            if sick_teacher_name.lower() in t["name"].lower():
                sick_teacher_id = t["id"]
                sick_teacher_obj = t
                break
        
        if not sick_teacher_id:
            return {"error": f"Teacher '{sick_teacher_name}' not found in database."}

        # 2. Find lessons for this teacher on this day
        sick_lessons = [l for l in schedule if l["teacher"] == sick_teacher_id]
        if time_slot:
            sick_lessons = [l for l in sick_lessons if l["time"] == time_slot]

        if not sick_lessons:
            return {"message": f"Teacher {sick_teacher_obj['name']} has no lessons on {day}."}

        replacements = []
        
        for lesson in sick_lessons:
            subject = lesson["subject"]
            time = lesson["time"]
            room = lesson["room"]
            
            # Find candidate: same subject + free at this time
            candidates = []
            for t in teachers:
                if t["id"] == sick_teacher_id: continue
                
                # Check if teaches same subject
                if subject in t["subjects"]:
                    # Check if free at this time
                    is_busy = any(l["teacher"] == t["id"] and l["time"] == time for l in schedule)
                    if not is_busy:
                        candidates.append({"id": t["id"], "name": t["name"], "reason": "Same subject expert"})

            # If no experts, find any free teacher
            if not candidates:
                for t in teachers:
                    if t["id"] == sick_teacher_id: continue
                    is_busy = any(l["teacher"] == t["id"] and l["time"] == time for l in schedule)
                    if not is_busy:
                        candidates.append({"id": t["id"], "name": t["name"], "reason": "Free during this slot"})
                        if len(candidates) >= 2: break # Don't return too many

            replacements.append({
                "original_lesson": f"{subject} in {room} at {time}",
                "candidates": candidates[:3] # Top 3 candidates
            })

        return {
            "sick_teacher": sick_teacher_obj["name"],
            "day": day,
            "replacements": replacements
        }

    def find_free_teachers(self, day: str, time_slot: str) -> List[Dict]:
        """
        Killer Feature: Find all teachers who have no lessons at this specific time.
        """
        teachers = self.data.get("teachers", [])
        schedule = self.data.get("schedule", {}).get(day, [])
        
        free_teachers = []
        for t in teachers:
            is_busy = any(l["teacher"] == t["id"] and l["time"] == time_slot for l in schedule)
            if not is_busy:
                free_teachers.append({"name": t["name"], "subjects": t["subjects"]})
        
        return free_teachers


# Global instance
scheduler = SchedulerService()
