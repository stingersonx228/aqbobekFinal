import sqlite3
import re

def normalize(name):
    if not name: return ""
    # Lowercase, strip, remove trailing slashes/punctuation
    name = str(name).lower().strip().rstrip('/')
    # Normalize spaces (e.g. 'дүние жүзі' -> 'дүниежүзі')
    name = name.replace(" ", "")
    return name

def cleanup_db():
    conn = sqlite3.connect('aqbobek.db')
    cursor = conn.cursor()

    # 1. Get all subjects
    cursor.execute("SELECT id, name FROM subjects")
    subjects = cursor.fetchall()

    seen = {} # normalized_name -> canonical_id
    merge_map = {} # old_id -> new_id

    for sid, name in subjects:
        norm = normalize(name)
        if norm in seen:
            merge_map[sid] = seen[norm]
            print(f"Merging Subject ID {sid} ('{name}') -> ID {seen[norm]}")
        else:
            seen[norm] = sid

    # 2. Update Foreign Keys in teacher_loads
    for old_id, new_id in merge_map.items():
        cursor.execute("UPDATE teacher_loads SET subject_id = ? WHERE subject_id = ?", (new_id, old_id))
        cursor.execute("UPDATE schedule SET subject_id = ? WHERE subject_id = ?", (new_id, old_id))
    
    # 3. Delete Duplicate Subjects
    if merge_map:
        ids_to_delete = tuple(merge_map.keys())
        if len(ids_to_delete) == 1:
            cursor.execute("DELETE FROM subjects WHERE id = ?", ids_to_delete)
        else:
            cursor.execute(f"DELETE FROM subjects WHERE id IN {ids_to_delete}")
    
    conn.commit()
    print(f"Cleanup complete. Merged {len(merge_map)} subjects.")

    # 4. Check for Teachers duplicates too?
    cursor.execute("SELECT id, name FROM teachers")
    teachers = cursor.fetchall()
    seen_t = {}
    merge_t = {}
    for tid, name in teachers:
        # Normalize teacher name: "Нажмадинов М." vs "Нажмадинов Марат"
        # We'll be more cautious here. Just match by surname if first letter matches.
        norm = name.strip().split()[0].lower() # Just surname
        if norm in seen_t:
            # Check if one is a prefix of another or vice versa
            if name.startswith(seen_t[norm][1]) or seen_t[norm][1].startswith(name):
                merge_t[tid] = seen_t[norm][0]
                print(f"Merging Teacher ID {tid} ('{name}') -> ID {seen_t[norm][0]} ('{seen_t[norm][1]}')")
        else:
            seen_t[norm] = (tid, name)

    for old_id, new_id in merge_t.items():
        cursor.execute("UPDATE teacher_loads SET teacher_id = ? WHERE teacher_id = ?", (new_id, old_id))
        cursor.execute("UPDATE schedule SET teacher_id = ? WHERE teacher_id = ?", (new_id, old_id))
    
    if merge_t:
        ids_to_delete = tuple(merge_t.keys())
        if len(ids_to_delete) == 1:
            cursor.execute("DELETE FROM teachers WHERE id = ?", ids_to_delete)
        else:
            cursor.execute(f"DELETE FROM teachers WHERE id IN {ids_to_delete}")
    
    conn.commit()
    print(f"Teacher cleanup complete. Merged {len(merge_t)} teachers.")
    
    conn.close()

if __name__ == "__main__":
    cleanup_db()
