import json
from pathlib import Path
ROOT = Path("data/kaipanla/raw")
for d in sorted(p.name for p in ROOT.iterdir() if (p/"zt_pool.json").exists()):
    if d < "2024-08-20" or d > "2024-09-06":
        continue
    data = json.loads((ROOT/d/"zt_pool.json").read_text(encoding="utf-8"))
    s = next((x for x in data["stocks"] if x["code"]=="603626"), None)
    if not s:
        print(d, "科森不在池")
        continue
    print(d, f"{s['boards']}板 theme={s['theme']} tags={s['theme_tags_text']} sec={s['sector_code']}")
