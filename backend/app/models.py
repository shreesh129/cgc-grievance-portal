from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base

def utcnow(): return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    login_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(30), index=True)
    password_hash: Mapped[str] = mapped_column(String(500), default="")
    department: Mapped[str | None] = mapped_column(String(120), nullable=True)
    designation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    mentor_login_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    source_system: Mapped[str] = mapped_column(String(80), default="local")
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    jti_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

class Complaint(Base):
    __tablename__ = "complaints"
    id: Mapped[int] = mapped_column(primary_key=True)
    tracking_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(80), index=True)
    user_name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(30), index=True)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False)
    portal: Mapped[str] = mapped_column(String(30), index=True)
    category: Mapped[str] = mapped_column(String(100), index=True)
    sub_category: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True)
    hostel: Mapped[str | None] = mapped_column(String(80), nullable=True)
    block_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    class_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lab_no: Mapped[str | None] = mapped_column(String(80), nullable=True)
    staffroom: Mapped[str | None] = mapped_column(String(100), nullable=True)
    target_authority: Mapped[str | None] = mapped_column(String(40), nullable=True)
    priority: Mapped[str] = mapped_column(String(20), default="low", index=True)
    status: Mapped[str] = mapped_column(String(30), default="filed", index=True)
    current_handler: Mapped[str] = mapped_column(String(40), index=True)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_action_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_escalated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voice_path: Mapped[str | None] = mapped_column(String(300), nullable=True)
    parent_complaint_id: Mapped[int | None] = mapped_column(ForeignKey("complaints.id"), nullable=True)

Index("ix_complaint_cluster", Complaint.category, Complaint.sub_category, Complaint.gender, Complaint.hostel, Complaint.block_no, Complaint.class_no, Complaint.lab_no)
Index("ix_complaint_handler_status", Complaint.current_handler, Complaint.status)
Index("ix_complaint_user_time", Complaint.user_id, Complaint.submitted_at)

class ComplaintEvent(Base):
    __tablename__ = "complaint_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    from_handler: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_handler: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    complaint_id: Mapped[int] = mapped_column(ForeignKey("complaints.id"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

Index("ix_feedback_unique_complaint", Feedback.complaint_id, unique=True)
