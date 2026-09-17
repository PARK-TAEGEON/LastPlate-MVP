import hashlib
import json

def stable_id(prefix, value):
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return prefix + "-" + hashlib.sha256(body.encode()).hexdigest()[:20]

def event_id(event):
    # Source+description distinguish independent observations with the same date.
    body=event.model_dump(mode="json", exclude={"event_id","source_text","matched_sources","reason"})
    # Additive release metadata must not change existing v0.2.2 event IDs.
    if body.get("action") is None:
        body.pop("action",None)
    if not body.get("superseded"):
        body.pop("superseded",None)
    return stable_id("event", body)

def deduplicate(events):
    found = {}
    for event in events:
        eid = event_id(event)
        found.setdefault(eid, event.model_copy(update={"event_id":eid}))
    return list(found.values())
