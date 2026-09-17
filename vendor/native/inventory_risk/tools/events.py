"""Small deterministic clause parser; partial extraction is never reported as ok."""
import re
from datetime import date, timedelta
from pydantic import ValidationError
from schemas.event import Event, EventParseResult
from schemas.errors import DataQualityError, input_error, validation_error
from .identity import deduplicate
from .ingredients import IngredientRegistry

DATE_PATTERN = r"\d{4}-\d{1,2}-\d{1,2}|오늘|내일|모레"
BOUNDARY = re.compile(r"추가하고|추가되고|증가하고|감소하고|빠지고|취소하고|그리고요|그리고|[;\n]|[.!?](?:\s+|$)")
RESTRICTION = re.compile(
    r"(?P<release>(?:사용\s*)?금지(?:는|를)?\s*(?:해제|취소)(?:해\s*주세요)?"
    r"|제외\s*취소(?:해\s*주세요)?|다시\s*사용(?:해\s*주세요)?"
    r"|사용\s*가능|(?:빼지|제외하지)\s*마세요)"
    r"|(?:쓰지|사용하지)(?:\s*(?:말아\s*주세요|말아주시고|말고|마세요))?"
    r"|(?:사용\s*)?금지|(?:꼭\s*)?빼\s*주세요|제외(?:해\s*주세요|하고)"
)

IGNORABLE = re.compile(r"(?:그리고요|그리고|또한|또|및|아니요)(?=\s|[,./;!?]|$)|[\s,./;!?]+")

def meaningful(text):
    """Only whole filler tokens/punctuation are ignored; never arbitrary suffixes."""
    return bool(IGNORABLE.sub("", text))

def strip_connectors(text):
    return re.sub(r"^(?:(?:그리고요|그리고|또한|또|및|아니요)(?=\s|[,./;!?]|$)|[\s,./;!?])+", "", text)

def attendance_residual(segment):
    # Conservative supported clause grammar, not a bag of removable keywords.
    text=strip_connectors(re.sub(DATE_PATTERN,"",segment)).strip()
    match=re.match(r"(?:(?:외부\s*)?(?:손님|인원|사람)(?:이|은|는)?\s*|회식으로\s*)?"
                   r"[+-]?\d+\s*명\s*(?:추가|증가|감소|취소|빠지)"
                   r"(?:됩니다|됐어요|해주세요|해 주세요|되고|하고|고|요)?",text)
    return text if not match else text[match.end():]

def split_segments(text):
    result=[]
    start=0
    for match in BOUNDARY.finditer(text):
        segment=text[start:match.end()].strip()
        if segment:
            result.append(segment)
        start=match.end()
    if text[start:].strip():
        result.append(text[start:].strip())
    return result

def dates_in(text,as_of):
    mentions=[]
    for token in re.findall(DATE_PATTERN,text):
        if token in {"오늘","내일","모레"}:
            mentions.append(as_of+timedelta(days={"오늘":0,"내일":1,"모레":2}[token]))
        else:
            try:
                mentions.append(date.fromisoformat(token))
            except ValueError as exc:
                raise input_error(f"Invalid date: {token}","user_event.date") from exc
    return mentions

def resolve_event(event,registry):
    if not event.ingredient:
        return event,None
    match=registry.resolve(event.ingredient)
    if match:
        return event.model_copy(update=match),None
    event=event.model_copy(update={"needs_clarification":True,"reason":"unregistered_ingredient"})
    warning=dict(type="unregistered_ingredient",ingredient=event.ingredient,
                 reason="unregistered_ingredient",message="등록된 식재료에서 해당 품목을 찾을 수 없습니다.",
                 matched_sources=[],source_text=event.source_text)
    return event,warning

def extract_restrictions(segment,when,registry):
    """Scan every predicate; comma lists share only their following predicate."""
    matches=list(RESTRICTION.finditer(segment))
    events=[];warnings=[];incomplete=False
    start=0
    for match in matches:
        prefix=strip_connectors(re.sub(DATE_PATTERN,"",segment[start:match.start()])).strip(" .;\n")
        source=segment if len(matches)==1 else segment[start:match.end()].strip(" ,.;\n")
        for raw_name in prefix.split(","):
            name=raw_name.strip()
            if not registry.resolve(name):
                name=re.sub(r"(?:가|이|은|는|을|를|도)$","",name).strip()
            if not name:
                incomplete=True
                continue
            release=match.group("release") is not None
            event=Event(event_type="ingredient_restriction_release_event" if release else "ingredient_restriction_event",ingredient=name,date=when,
                        end_date=when,restriction=None if release else "do_not_use",
                        action="release_restriction" if release else None,needs_clarification=when is None,
                        description=source,source_text=source)
            event,warning=resolve_event(event,registry)
            events.append(event)
            if warning:
                warnings.append(warning)
        start=match.end()
        # Commas between complete clauses are not empty list items.
        while start<len(segment) and segment[start] in " ,;\n":
            start+=1
    incomplete = incomplete or meaningful(segment[start:])
    return events,warnings,incomplete

def merge_restrictions(events):
    """Only equivalent user restrictions merge; preserve both original phrases."""
    merged=[];positions={}
    for event in events:
        if event.event_type=="ingredient_restriction_release_event":
            # A release is an ordering barrier: ban -> release -> ban must survive.
            positions={k:v for k,v in positions.items() if k[0]!=event.ingredient}
        if event.event_type!="ingredient_restriction_event":
            merged.append(event)
            continue
        key=(event.ingredient,event.date,event.end_date,event.restriction,
             event.needs_clarification,event.source_type)
        if key not in positions:
            positions[key]=len(merged)
            merged.append(event)
            continue
        index=positions[key]
        previous=merged[index]
        source="\n".join(dict.fromkeys([previous.source_text or previous.description,
                                      event.source_text or event.description]))
        merged[index]=previous.model_copy(update={"source_text":source,"description":source})
    return merged

def resolve_restriction_order(events):
    """Input order wins for identical normalized ingredient/date scopes only.

    History stays visible. Undated/unresolved events still require clarification.
    Different or overlapping (nonidentical) scopes are never silently overridden.
    """
    result=[]; latest={}; trace=[]
    kinds={"ingredient_restriction_event","ingredient_restriction_release_event"}
    for event in events:
        if event.event_type in kinds:
            key=(event.ingredient,event.date,event.end_date)
            if key in latest:
                index=latest[key]
                previous=result[index]
                result[index]=previous.model_copy(update={"superseded":True})
                trace.append(f"Restriction intent: {previous.event_type} -> {event.event_type}; {event.ingredient}; {event.date}; last explicit intent wins")
            latest[key]=len(result)
            trace.append(f"Restriction intent: {event.event_type}; {event.ingredient}; {event.date}; source={event.source_text or event.description}")
        result.append(event)
    return result,trace

def _parse_result(value,as_of,registry):
    if value is None:
        return EventParseResult(status="ok")
    if isinstance(value,(dict,Event)):
        try:
            event=Event.model_validate(value.model_dump() if isinstance(value,Event) else value)
        except ValidationError as exc:
            raise validation_error(exc,prefix="user_event.") from exc
        if event.date is None:
            event=event.model_copy(update={"needs_clarification":True})
        event,warning=resolve_event(event,registry)
        return EventParseResult(status="needs_clarification" if event.needs_clarification else "ok",
                                parsed_events=deduplicate([event]),validation_warnings=[warning] if warning else [])
    if not isinstance(value,str) or not value.strip():
        raise input_error("user_event must be non-empty text or an Event object","user_event")
    segments=split_segments(value)
    # Validate all dates before emitting any events.
    mentions=[dates_in(segment,as_of) for segment in segments]
    inherited=mentions[0][0] if mentions and len(mentions[0])==1 else None
    events=[];unparsed=[];warnings=[]
    for segment,dates in zip(segments,mentions):
        if not meaningful(segment):
            continue
        when=dates[0] if len(dates)==1 else inherited if not dates else None
        extracted=[]
        if any(x in segment for x in ("인원","손님","사람")) or re.search(r"\d+\s*명",segment):
            numbers=re.findall(r"(?<![\d.])([+-]?\d+)\s*명",segment)
            ambiguous=any(x in segment for x in ("정도","약","~","에서","쯤","대략")) or bool(re.search(r"\d[.,]\d|\d+\s*-\s*\d+\s*명",segment))
            adding="추가" in segment or "증가" in segment
            removing=any(x in segment for x in ("감소","취소","빠지","빠지고","빠집"))
            delta=int(numbers[0]) if len(numbers)==1 and not ambiguous and adding!=removing else None
            if delta is not None and removing:
                delta=-abs(delta)
            extracted.append(Event(event_type="attendance_event",date=when,attendance_delta=delta,
                                   needs_clarification=delta is None or when is None,description=segment,source_text=segment,
                                   reason="회식" if "회식" in segment else "외부 손님" if "손님" in segment or "외부" in segment else None))
            if delta is not None and meaningful(attendance_residual(segment)):
                unparsed.append(segment)
        restriction=RESTRICTION.search(segment)
        expiry=re.search(r"까지|유통기한",segment)
        if restriction:
            restrictions,restriction_warnings,incomplete=extract_restrictions(segment,when,registry)
            extracted.extend(restrictions)
            warnings.extend(restriction_warnings)
            if incomplete:
                unparsed.append(segment)
        intent=expiry if not restriction else None
        if intent:
            prefix=re.sub(DATE_PATTERN,"",segment[:intent.start()]).strip(" .,;")
            if not registry.resolve(prefix):
                prefix=re.sub(r"(?:가|이|은|는|을|를)$","",prefix).strip()
            # Exact registered names/aliases only; unfamiliar phrases are not guessed.
            if prefix:
                kind="ingredient_restriction_event" if restriction else "expiry_event"
                event=Event(event_type=kind,ingredient=prefix,date=when,end_date=when if restriction else None,
                            restriction="do_not_use" if restriction else None,needs_clarification=when is None,
                            description=segment,source_text=segment)
                event,warning=resolve_event(event,registry)
                extracted.append(event)
                if warning:
                    warnings.append(warning)
                tail=segment[intent.end():]
                tail=re.sub(r"^(?:예요|에요|입니다|이에요)?", "", tail)
                if meaningful(tail):
                    unparsed.append(segment)
        if extracted:
            events.extend(extracted)
            if restriction and expiry:
                # This clause has two ingredient intents but no supported boundary.
                # Preserve it for confirmation rather than silently drop the second.
                unparsed.append(segment)
        else:
            unparsed.append(segment)
    status="partial" if events and unparsed else "needs_clarification" if unparsed or any(e.needs_clarification for e in events) else "ok"
    events,trace=resolve_restriction_order(merge_restrictions(events))
    return EventParseResult(status=status,parsed_events=deduplicate(events),unparsed_segments=unparsed,validation_warnings=warnings,decision_trace=trace)

def parse_event_result(value,as_of,ingredients,aliases=None):
    registry=ingredients if isinstance(ingredients,IngredientRegistry) else IngredientRegistry({"provided":ingredients},aliases)
    try:
        return _parse_result(value,as_of,registry)
    except DataQualityError as exc:
        return EventParseResult(status="invalid_input",errors=[exc.detail.model_dump(mode="json")])

def events_from_result(result):
    return deduplicate(result.parsed_events+[
        Event(event_type="unparsed_event",needs_clarification=True,reason="unparsed_segment",
              description=segment,source_text=segment) for segment in result.unparsed_segments])

def parse_event(value,as_of,ingredients):
    """Backward-compatible list API; the richer result is parse_event_result()."""
    result=parse_event_result(value,as_of,ingredients)
    if result.errors:
        detail=result.errors[0]
        raise DataQualityError(detail["message"],file=detail["file"],row=detail["row"],field=detail["field"],code=detail["code"])
    return events_from_result(result)

def applies(event,day):
    return not event.superseded and not event.needs_clarification and event.date is not None and event.date<=day<=(event.end_date or event.date)
