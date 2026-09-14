from datetime import datetime,timedelta,timezone
from sqlalchemy import select,func,and_
from sqlalchemy.ext.asyncio import AsyncSession
from .models import Complaint

async def count_matching_recent(db,c,minutes):
    since=datetime.now(timezone.utc)-timedelta(minutes=minutes)
    stmt=select(func.count(Complaint.id)).where(
        Complaint.submitted_at>=since,
        Complaint.category==c.category, Complaint.sub_category==c.sub_category,
        Complaint.gender==c.gender, Complaint.hostel==c.hostel,
        Complaint.block_no==c.block_no, Complaint.class_no==c.class_no,
        Complaint.lab_no==c.lab_no)
    return int((await db.execute(stmt)).scalar_one())

async def count_last_45_minutes(db):
    since=datetime.now(timezone.utc)-timedelta(minutes=45)
    return int((await db.execute(select(func.count(Complaint.id)).where(Complaint.submitted_at>=since))).scalar_one())

async def calculate_priority(db,c):
    n=await count_matching_recent(db,c,5)
    surge=await count_last_45_minutes(db)>=50
    if surge or n>20:return "high"
    if n>10:return "medium"
    return "low"
