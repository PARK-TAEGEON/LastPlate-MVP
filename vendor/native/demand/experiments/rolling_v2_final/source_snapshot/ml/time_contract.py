from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .errors import TimeContractError

def utc_now():
    """Server clock. Tests replace this function; clients cannot supply now."""
    return datetime.now(timezone.utc)

def aware_timestamp(value):
    try:
        d = datetime.fromisoformat(value.replace('Z','+00:00'))
        if d.tzinfo is None or d.utcoffset() is None:
            raise ValueError('missing offset')
        return d.astimezone(timezone.utc)
    except (ValueError,TypeError,AttributeError) as exc:
        raise TimeContractError('Use an ISO-8601 timestamp with explicit UTC offset') from exc

def target_date(value):
    try:
        d = date.fromisoformat(value)
        if d.isoformat() != value:
            raise ValueError('noncanonical date')
        return d
    except (ValueError,TypeError) as exc:
        raise TimeContractError('target date must be YYYY-MM-DD') from exc

@dataclass(frozen=True)
class ServiceConfig:
    storage_dir: Path
    model_dir: Path
    timezone: str
    cutoff_time: str
    actual_ready_time: str
    mode: str = 'operation'
    deadline_days_before: int = 0
    trusted_weather_sources: tuple = ('KMA_ASOS',)

    def __post_init__(self):
        for key in ('storage_dir','model_dir'):
            path = Path(getattr(self,key))
            if not path.is_absolute():
                raise ValueError(f'{key} must be an explicit absolute path')
            object.__setattr__(self,key,path.resolve())
        if self.mode not in ('operation','replay','demo'):
            raise ValueError('mode must be operation/replay/demo')
        if type(self.deadline_days_before) is not int or self.deadline_days_before < 0:
            raise ValueError('deadline_days_before must be a nonnegative integer')
        try:
            ZoneInfo(self.timezone)
            for value in (self.cutoff_time,self.actual_ready_time):
                t=time.fromisoformat(value)
                if t.tzinfo is not None or len(value)!=5:
                    raise ValueError('Use local HH:MM times')
            if self.deadline_days_before == 0 and self.cutoff_time >= self.actual_ready_time:
                raise ValueError('Actual-ready time must follow same-day cutoff')
        except (ValueError,ZoneInfoNotFoundError) as exc:
            raise TimeContractError(str(exc)) from exc

    def local_instant(self,day,value):
        naive=datetime.combine(day,time.fromisoformat(value))
        zone=ZoneInfo(self.timezone)
        a,b=naive.replace(tzinfo=zone,fold=0),naive.replace(tzinfo=zone,fold=1)
        if a.utcoffset()!=b.utcoffset() or a.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)!=naive:
            raise TimeContractError('Ambiguous or nonexistent local policy time')
        return a.astimezone(timezone.utc)

    def deadline(self,target):
        return self.local_instant(target_date(target)-timedelta(days=self.deadline_days_before),self.cutoff_time)

    def actual_ready(self,target):
        return self.local_instant(target_date(target),self.actual_ready_time)

    @property
    def database(self):
        return self.storage_dir/self.mode/'service.sqlite3'

    def contract(self):
        return dict(timezone=self.timezone,cutoff_time=self.cutoff_time,
                    actual_ready_time=self.actual_ready_time,deadline_days_before=self.deadline_days_before,mode=self.mode)
