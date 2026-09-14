from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from .models import Complaint

async def detect_duplicate(db: AsyncSession, data):
    since=datetime.now(timezone.utc)-timedelta(hours=24)
    q=select(Complaint).where(
        Complaint.user_id==data.user_id,
        Complaint.category==data.category.strip(),
        Complaint.sub_category==data.sub_category.strip(),
        Complaint.submitted_at>=since,
        Complaint.status.not_in(["closed"])
    ).order_by(Complaint.submitted_at.desc()).limit(1)
    return (await db.execute(q)).scalar_one_or_none()

async def enforce_submission_limits(db: AsyncSession, user_id: str, role: str):
    # Fair anti-abuse limits: several legitimate reports are allowed.
    since=datetime.now(timezone.utc)-timedelta(minutes=30)
    n=int((await db.execute(select(func.count(Complaint.id)).where(
        Complaint.user_id==user_id, Complaint.submitted_at>=since
    ))).scalar_one())
    limit=8 if role=="student" else 12
    if n>=limit:
        raise HTTPException(429,f"Too many complaints submitted recently. Please try again later.")
