import asyncio
import os
import sys
import json

# Add current directory to path
sys.path.append(os.getcwd())

from src.scheduler_service import scheduler

async def test_scheduler():
    results = {}
    
    # Try a known teacher from the excel data
    results['replacement'] = await scheduler.find_replacement("Арыстанғалиқызы А.", "Дүйсенбі")
    
    # Try free teachers
    results['free'] = await scheduler.find_free_teachers("Дүйсенбі", "08:00")
    
    with open('scratch/scheduler_test_results.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    asyncio.run(test_scheduler())
