from datetime import datetime,timezone,timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from .models import Complaint,ComplaintEvent
from .routing import next_handler
from .config import settings

def working_days_elapsed(start,now=None):
    now=now or datetime.now(timezone.utc)
    if start.tzinfo is None:start=start.replace(tzinfo=timezone.utc)
    if start>=now:return 0
    days=0;cur=start
    while cur.date()<now.date():
        cur=(cur+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
        if cur.weekday()<5:days+=1
    return days

async def run_escalation_pass(db:AsyncSession):
    rows=(await db.execute(select(Complaint).where(
        Complaint.status.not_in(["resolved","closed"]),
        Complaint.escalation_level<5))).scalars().all()
    changed=[]
    for c in rows:
        if working_days_elapsed(c.last_action_at)<settings.escalation_days:continue
        nxt=next_handler(c.current_handler)
        if not nxt:continue
        old=c.current_handler
        now=datetime.now(timezone.utc)
        c.current_handler=nxt;c.escalation_level+=1;c.last_escalated=now;c.last_action_at=now;c.status="escalated"
        db.add(ComplaintEvent(complaint_id=c.id,event_type="auto_escalation",from_handler=old,to_handler=nxt,note=f"No resolution within {settings.escalation_days} working days"))
        changed.append(c.tracking_id)
    if changed:await db.commit()
    return changed
