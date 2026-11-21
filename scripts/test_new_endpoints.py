import sys
sys.path.insert(0, '.')
from src.appliers.wellfound_discovery import discover_live_wellfound_jobs

# Let's test discovery with limit=20
jobs = discover_live_wellfound_jobs(limit=20)
print(f"Discovered {len(jobs)} jobs:")
for j in jobs:
    print(f"  - {j['company']} | {j['title']} | {j['url']}")
