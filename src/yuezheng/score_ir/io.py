import json
from dataclasses import asdict
from pathlib import Path
from .model import Event, Measure, Part, Score, SourceRef, Staff

def _source(value): return SourceRef(**value) if value else None

def score_from_dict(data):
    parts=[]
    for p in data.get("parts", []):
        staves=[]
        for s in p.get("staves", []):
            measures=[]
            for m in s.get("measures", []):
                values=dict(m); values["source"]=_source(values.get("source"))
                values["events"]=[]
                for e in m.get("events", []):
                    ev=dict(e); ev["source"]=_source(ev.get("source")); values["events"].append(Event(**ev))
                measures.append(Measure(**values))
            staves.append(Staff(id=s["id"], clef=s.get("clef", "treble"), measures=measures))
        parts.append(Part(id=p["id"], name=p["name"], instrument_id=p["instrument_id"], transposition=p.get("transposition"), staves=staves))
    return Score(title=data["title"], pitch_mode=data.get("pitch_mode", "written"), metadata=data.get("metadata", {}), parts=parts)

def load_score(path): return score_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
def save_score(score, path): Path(path).write_text(json.dumps(asdict(score), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
