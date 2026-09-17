"""Isolated adapter to the original Inventory & Risk event parser. No new parser."""
import sys, json
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[2] / 'vendor/native'
sys.path.insert(0, str(ROOT / 'inventory_risk'))
from tools.events import parse_event_result, events_from_result, applies, resolve_restriction_order, merge_restrictions
from tools.identity import deduplicate

value = json.load(sys.stdin)
events, diagnostics = [], []
for item in value['events']:
    report = parse_event_result(item, date.fromisoformat(value['as_of']), value['ingredients'])
    diagnostics.append(report.model_dump(mode='json'))
    events.extend(events_from_result(report))
events, _ = resolve_restriction_order(merge_restrictions(events))
events = deduplicate(events)
active = [e for e in events if e.event_type == 'attendance_event' and applies(e, date.fromisoformat(value['target_date']))]
print(json.dumps({'events': [e.model_dump(mode='json') for e in events], 'diagnostics': diagnostics,
                  'attendance_delta': sum(e.attendance_delta for e in active)}, ensure_ascii=False, allow_nan=False))
