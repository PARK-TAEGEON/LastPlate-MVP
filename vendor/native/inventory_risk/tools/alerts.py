from schemas.alert import Alert, ALERT_ALIASES

def make_alert(config, kind, message, evidence, *, severity=None, **context):
    kind = ALERT_ALIASES.get(kind,kind)
    known = {k:context.pop(k) for k in list(context) if k in {"ingredient","candidate_id","candidate_action","cause_event_ids"}}
    return Alert(type=kind, severity=severity or config.severity(kind), message=message,
                 evidence=evidence, details=context, **known).model_dump(mode="json")
