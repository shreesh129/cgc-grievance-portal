import os, uuid, asyncio, json, csv, io, hashlib, secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Header, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from .database import Base,engine,get_db,SessionLocal,migrate_schema
from .models import User,Session,Complaint,ComplaintEvent,Feedback
from .schemas import LoginRequest,ComplaintText,StatusUpdate,Readdressal,FeedbackIn,IntegratedUser,DeveloperConfig
from .security import ROLES,AUTHORITIES,hash_password,verify_password,create_token,bearer,decode_token,validate_password
from .catalog import *
from .routing import initial_handler,next_handler,CHAIN
from .priority import calculate_priority,count_last_45_minutes
from .escalation import run_escalation_pass
from .anti_spam import enforce_submission_limits,detect_duplicate
from .config import settings

FAILED_LIMIT=5
LOCK_MINUTES=15
RATE_WINDOW=timedelta(minutes=1)
RATE_LIMIT=60
_request_hits={}

def now(): return datetime.now(timezone.utc)

def client_key(request:Request):
    return request.client.host if request.client else "unknown"

async def cleanup_rate():
    cutoff=now()-RATE_WINDOW
    for k,v in list(_request_hits.items()):
        _request_hits[k]=[t for t in v if t>=cutoff]
        if not _request_hits[k]: _request_hits.pop(k,None)

async def rate_limit(request:Request):
    await cleanup_rate()
    k=client_key(request); hits=_request_hits.setdefault(k,[])
    if len(hits)>=RATE_LIMIT: raise HTTPException(429,"Too many requests. Please try again shortly.")
    hits.append(now())

async def escalation_loop():
    while True:
        try:
            async with SessionLocal() as db: await run_escalation_pass(db)
        except asyncio.CancelledError: raise
        except Exception as e: print("Escalation pass error:",e)
        await asyncio.sleep(300)

@asynccontextmanager
async def lifespan(app):
    Path(settings.upload_dir).mkdir(parents=True,exist_ok=True)
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    await migrate_schema()
    async with SessionLocal() as db:
        admin=(await db.execute(select(User).where(User.login_id==settings.bootstrap_admin_id))).scalar_one_or_none()
        if not admin:
            # For first run, generate a password unless the operator explicitly supplied one.
            pw=settings.bootstrap_admin_password or secrets.token_urlsafe(12)
            if not settings.bootstrap_admin_password:
                print(f"\n[MESSAGE] First-run admin credentials: {settings.bootstrap_admin_id} / {pw}\n")
            db.add(User(login_id=settings.bootstrap_admin_id,name=settings.bootstrap_admin_name,role="administration",
                        password_hash=hash_password(pw),source_system="bootstrap"))
            await db.commit()
    task=asyncio.create_task(escalation_loop())
    yield
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass
    await engine.dispose()

app=FastAPI(title="MessAudit Grievance Portal",version="5.0.0",lifespan=lifespan)

origins=[x.strip() for x in settings.cors_origins.split(",") if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=True,allow_methods=["GET","POST","PATCH","PUT","OPTIONS"],allow_headers=["Authorization","Content-Type"])

@app.middleware("http")
async def security_headers(request:Request,call_next):
    await rate_limit(request)
    response=await call_next(request)
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Referrer-Policy"]="no-referrer"
    response.headers["Permissions-Policy"]="microphone=(self)"
    return response

@app.get("/")
async def root():
    return {"service":"MessAudit Grievance Portal","status":"online","version":"5.0.0","security":"hardened demo configuration"}

@app.get("/api/health")
async def health():
    return {"status":"ok","version":"5.0.0","features":["password-authentication","role-portals","college-erp-integration","developer-mode","sqlite-wal","45-minute-surge-trigger","rate-limiting","duplicate-detection","audit-trail","live-dashboard","14-working-day-escalation","voice-complaints","feedback","readdressal"]}

@app.get("/api/catalog")
async def catalog():
    return {"hostels":HOSTELS,"room_issues":ROOM_ISSUES,"bathroom_issues":BATHROOM_ISSUES,"college_issues":COLLEGE_ISSUES,"common_issues":COMMON_ISSUES,"mess_issues":MESS_ISSUES,"staffroom_issues":STAFFROOM_ISSUES}

async def current_user(db,payload):
    u=(await db.execute(select(User).where(User.login_id==payload["sub"]))).scalar_one_or_none()
    if not u or not u.active: raise HTTPException(401,"Account is inactive or missing")
    # Session revocation is checked when jti is present.
    jti=payload.get("jti")
    if jti:
        jh=hashlib.sha256(jti.encode()).hexdigest()
        s=(await db.execute(select(Session).where(Session.jti_hash==jh))).scalar_one_or_none()
        if not s or s.revoked or s.expires_at<=now(): raise HTTPException(401,"Session expired or revoked")
    return u

async def auth(request:Request,db:AsyncSession):
    p=bearer(request.headers.get("authorization"))
    return await current_user(db,p),p

@app.post("/api/login")
async def login(req:LoginRequest,request:Request,db:AsyncSession=Depends(get_db)):
    u=(await db.execute(select(User).where(User.login_id==req.login_id.strip()))).scalar_one_or_none()
    if not u or not u.active:
        raise HTTPException(401,"Invalid login ID or password")
    if u.locked_until and u.locked_until>now(): raise HTTPException(429,"Account temporarily locked. Try again later.")
    if not u.password_hash or not verify_password(req.password,u.password_hash):
        u.failed_logins+=1
        if u.failed_logins>=FAILED_LIMIT: u.locked_until=now()+timedelta(minutes=LOCK_MINUTES);u.failed_logins=0
        await db.commit()
        raise HTTPException(401,"Invalid login ID or password")
    u.failed_logins=0;u.locked_until=None
    if req.portal:
        p=req.portal.lower()
        allowed=(u.role=="student" and p=="student") or (u.role=="teacher" and p=="teacher") or (u.role in AUTHORITIES and p==u.role)
        if not allowed: raise HTTPException(403,"This account cannot access that portal")
    access=create_token(u.login_id,u.role,u.name,"access")
    payload=decode_token(access)
    exp=datetime.fromtimestamp(payload["exp"],timezone.utc)
    db.add(Session(user_id=u.id,jti_hash=hashlib.sha256(payload["jti"].encode()).hexdigest(),expires_at=exp))
    await db.commit()
    return {"authenticated":True,"access_token":access,"token_type":"bearer","role":u.role,
            "login_id":u.login_id,"name":u.name,"portal":u.role,"anonymous_submission_allowed":u.role in {"student","teacher"}}

@app.post("/api/logout")
async def logout(request:Request,db:AsyncSession=Depends(get_db)):
    u,p=await auth(request,db)
    jti=p.get("jti")
    if jti:
        s=(await db.execute(select(Session).where(Session.jti_hash==hashlib.sha256(jti.encode()).hexdigest()))).scalar_one_or_none()
        if s:s.revoked=True
    await db.commit(); return {"logged_out":True}

def complaint_out(c, include_private=False):
    d={"tracking_id":c.tracking_id,"status":c.status,"priority":c.priority,"assigned_to":c.current_handler,
       "anonymous":c.is_anonymous,"portal":c.portal,"category":c.category,"sub_category":c.sub_category,
       "description":c.description,"gender":c.gender,"hostel":c.hostel,"block_no":c.block_no,"class_no":c.class_no,
       "lab_no":c.lab_no,"staffroom":c.staffroom,"target_authority":c.target_authority,
       "submitted_at":c.submitted_at,"last_action_at":c.last_action_at,"resolved_at":c.resolved_at,
       "escalation_level":c.escalation_level,"voice_available":bool(c.voice_path),"parent_tracking_id":None}
    if c.parent_complaint_id: d["parent_tracking_id"]=c.parent_complaint_id
    if include_private: d["user_id"]=c.user_id;d["user_name"]=c.user_name
    return d

async def get_complaint_row(db,tracking_id):
    return (await db.execute(select(Complaint).where(Complaint.tracking_id==tracking_id.strip()))).scalar_one_or_none()

def authority_can_view(u,c):
    # Authorities only see complaints currently assigned to their authority.
    return u.role in AUTHORITIES and c.current_handler==u.role

async def complaint_events(db,cid):
    rows=(await db.execute(select(ComplaintEvent).where(ComplaintEvent.complaint_id==cid).order_by(ComplaintEvent.created_at.asc()))).scalars().all()
    return [{"event_type":e.event_type,"from_handler":e.from_handler,"to_handler":e.to_handler,"note":e.note,"created_at":e.created_at} for e in rows]

async def create_complaint(db,data,voice=None,actor=None):
    if actor and (actor.role!=data.role or actor.login_id!=data.user_id): raise HTTPException(403,"Complaint identity does not match authenticated account")
    if data.anonymous and data.role not in {"student","teacher"}: raise HTTPException(403,"Only students and teachers may submit anonymously")
    if data.role=="student" and "mentor" in data.sub_category.lower().replace(" ","_"): data.target_authority="administration"
    if not data.anonymous and not data.user_name.strip(): raise HTTPException(400,"Name required unless anonymous")
    if data.role=="student" and data.portal not in {"college","hostel","common","mess"}: raise HTTPException(403,"Invalid student portal")
    if data.role=="teacher" and data.portal not in {"college","hostel","common","mess","hr","staffroom"}: raise HTTPException(403,"Invalid teacher portal")
    if data.portal in {"hr","staffroom"} and data.role!="teacher": raise HTTPException(403,"Teacher-only portal")
    if data.role=="teacher" and data.target_authority not in {"administration","hod"}: raise HTTPException(400,"Teacher complaints must select Administration or HOD")
    if data.portal=="hostel" and not data.hostel: raise HTTPException(400,"Hostel is required for hostel complaints")
    if len(data.description.strip())<10: raise HTTPException(400,"Please provide at least 10 characters describing the issue")
    await enforce_submission_limits(db,data.user_id,data.role)
    dup=await detect_duplicate(db,data)
    if dup: raise HTTPException(409,{"message":"A similar complaint was already submitted in the last 24 hours.","tracking_id":dup.tracking_id})
    handler,level=initial_handler(data.role,data.sub_category,data.target_authority)
    c=Complaint(tracking_id="GRV-"+uuid.uuid4().hex[:10].upper(),user_id=data.user_id,
        user_name=data.user_name.strip() if not data.anonymous else "Anonymous",role=data.role,is_anonymous=data.anonymous,
        portal=data.portal,category=data.category.strip(),sub_category=data.sub_category.strip(),description=data.description.strip(),
        gender=data.gender,hostel=data.hostel,block_no=data.block_no,class_no=data.class_no,lab_no=data.lab_no,
        staffroom=data.staffroom,target_authority=data.target_authority,current_handler=handler,escalation_level=level)
    db.add(c); await db.flush()
    if voice:
        if not voice.content_type or voice.content_type.lower() not in {"audio/webm","audio/ogg","audio/wav","audio/x-wav","audio/mpeg","audio/mp4","audio/aac"}:
            raise HTTPException(400,"Unsupported audio type")
        raw=await voice.read()
        if not raw: raise HTTPException(400,"Empty voice file")
        if len(raw)>settings.max_audio_mb*1024*1024: raise HTTPException(413,f"Voice file exceeds {settings.max_audio_mb} MB")
        ext={ "audio/webm":".webm","audio/ogg":".ogg","audio/wav":".wav","audio/x-wav":".wav","audio/mpeg":".mp3","audio/mp4":".m4a","audio/aac":".aac"}.get(voice.content_type.lower(),".audio")
        safe_name=f"{c.tracking_id}{ext}";path=os.path.abspath(os.path.join(settings.upload_dir,safe_name))
        if os.path.commonpath([path,os.path.abspath(settings.upload_dir)])!=os.path.abspath(settings.upload_dir): raise HTTPException(400,"Invalid upload path")
        with open(path,"wb") as f:f.write(raw)
        c.voice_path=path
    c.priority=await calculate_priority(db,c)
    surge_count=await count_last_45_minutes(db)
    db.add(ComplaintEvent(complaint_id=c.id,event_type="filed",to_handler=handler,note=f"Initial priority: {c.priority}"))
    if surge_count>=50: db.add(ComplaintEvent(complaint_id=c.id,event_type="surge_trigger",to_handler=handler,note=f"50+ complaints in rolling 45-minute window ({surge_count})."))
    await db.commit();await db.refresh(c);return complaint_out(c)

@app.post("/api/complaints")
async def submit(data:ComplaintText,request:Request,db:AsyncSession=Depends(get_db)):
    u,_=await auth(request,db);return await create_complaint(db,data,actor=u)

@app.post("/api/complaints/with-voice")
async def submit_voice(payload:str=Form(...),voice:UploadFile=File(...),request:Request=None,db:AsyncSession=Depends(get_db)):
    u,_=await auth(request,db)
    try:data=ComplaintText.model_validate(json.loads(payload))
    except Exception:raise HTTPException(400,"Invalid complaint payload")
    return await create_complaint(db,data,voice,u)

@app.get("/api/complaints/{tracking_id}")
async def get_one(tracking_id:str,request:Request,db:AsyncSession=Depends(get_db)):
    u,_=await auth(request,db);c=await get_complaint_row(db,tracking_id)
    if not c:raise HTTPException(404,"Complaint not found")
    if c.user_id!=u.login_id and not authority_can_view(u,c):raise HTTPException(403,"Not authorized to view this complaint")
    out=complaint_out(c,include_private=(c.user_id==u.login_id))
    out["events"]=await complaint_events(db,c.id)
    return out

@app.get("/api/complaints/{tracking_id}/voice")
async def voice(tracking_id:str,request:Request,db:AsyncSession=Depends(get_db)):
    u,_=await auth(request,db);c=await get_complaint_row(db,tracking_id)
    if not c or not c.voice_path:raise HTTPException(404,"Voice recording not found")
    if c.user_id!=u.login_id and not authority_can_view(u,c):raise HTTPException(403,"Not authorized")
    if not os.path.exists(c.voice_path):raise HTTPException(404,"Voice recording unavailable")
    return FileResponse(c.voice_path,media_type="application/octet-stream",filename=os.path.basename(c.voice_path))

@app.get("/api/complaints")
async def list_complaints(request:Request,handler:str|None=None,priority:str|None=None,status:str|None=None,limit:int=50,db:AsyncSession=Depends(get_db)):
    u,_=await auth(request,db)
    if u.role not in AUTHORITIES:raise HTTPException(403,"Authority access required")
    limit=max(1,min(limit,100))
    q=select(Complaint).where(Complaint.current_handler==u.role).order_by(Complaint.submitted_at.desc()).limit(limit)
    if handler and handler!=u.role: return []
    if priority:q=q.where(Complaint.priority==priority)
    if status:q=q.where(Complaint.status==status)
    return [complaint_out(x) for x in (await db.execute(q)).scalars().all()]

@app.post("/api/complaints/{tracking_id}/update")
async def update_complaint(tracking_id:str,data:StatusUpdate,request:Request,db:AsyncSession=Depends(get_db)):
    u,_=await auth(request,db);c=await get_complaint_row(db,tracking_id)
    if not c:raise HTTPException(404,"Complaint not found")
    if u.role!=c.current_handler:raise HTTPException(403,"Only the current authority may act")
    old=c.status; c.status=data.status;c.last_action_at=now()
    if data.status in {"resolved","closed"}:c.resolved_at=c.last_action_at
    db.add(ComplaintEvent(complaint_id=c.id,event_type="status_update",from_handler=u.role,note=f"{old} -> {data.status}: {data.note.strip()}"))
    await db.commit();await db.refresh(c);return complaint_out(c)

@app.post("/api/complaints/{tracking_id}/readdressal")
async def readdressal(tracking_id:str,data:Readdressal,request:Request,db:AsyncSession=Depends(get_db)):
    u,_=await auth(request,db);c=await get_complaint_row(db,tracking_id)
    if not c:raise HTTPException(404,"Complaint not found")
    if u.login_id!=c.user_id:raise HTTPException(403,"Only the original complainant may request readdressal")
    c.status="filed";c.last_action_at=now();c.resolved_at=None
    db.add(ComplaintEvent(complaint_id=c.id,event_type="readdressal",from_handler=u.role if u.role in AUTHORITIES else None,to_handler=c.current_handler,note=data.reason.strip()))
    await db.commit();await db.refresh(c)
    return {"status":"readdressal_recorded","complaint":complaint_out(c)}

@app.post("/api/complaints/{tracking_id}/feedback")
async def feedback(tracking_id:str,data:FeedbackIn,request:Request,db:AsyncSession=Depends(get_db)):
    u,_=await auth(request,db);c=await get_complaint_row(db,tracking_id)
    if not c or c.user_id!=u.login_id:raise HTTPException(403,"Not authorized")
    existing=(await db.execute(select(Feedback).where(Feedback.complaint_id==c.id))).scalar_one_or_none()
    if existing:raise HTTPException(409,"Feedback has already been submitted for this complaint")
    if c.status not in {"resolved","closed"}:raise HTTPException(400,"Feedback can be submitted after resolution")
    db.add(Feedback(complaint_id=c.id,rating=data.rating,comment=data.comment));db.add(ComplaintEvent(complaint_id=c.id,event_type="feedback",note=f"Rating: {data.rating}/5"))
    await db.commit();return {"status":"feedback_recorded","rating":data.rating}

@app.get("/api/complaints/{tracking_id}/feedback")
async def get_feedback(tracking_id:str,request:Request,db:AsyncSession=Depends(get_db)):
    u,_=await auth(request,db);c=await get_complaint_row(db,tracking_id)
    if not c or (c.user_id!=u.login_id and not authority_can_view(u,c)):raise HTTPException(403,"Not authorized")
    f=(await db.execute(select(Feedback).where(Feedback.complaint_id==c.id))).scalar_one_or_none()
    return None if not f else {"rating":f.rating,"comment":f.comment,"created_at":f.created_at}

@app.get("/api/admin/dashboard")
async def dashboard(request:Request,db:AsyncSession=Depends(get_db)):
    u,_=await auth(request,db)
    if u.role not in AUTHORITIES:raise HTTPException(403,"Authority access required")
    async def count(**kw):
        q=select(func.count(Complaint.id)).where(Complaint.current_handler==u.role)
        for k,v in kw.items():q=q.where(getattr(Complaint,k)==v)
        return int((await db.execute(q)).scalar_one())
    n=await count_last_45_minutes(db)
    return {"role":u.role,"total":await count(),"high":await count(priority="high"),"medium":await count(priority="medium"),"low":await count(priority="low"),
            "open":int((await db.execute(select(func.count(Complaint.id)).where(Complaint.current_handler==u.role,Complaint.status.not_in(["resolved","closed"])))).scalar_one()),
            "resolved":await count(status="resolved"),"escalated":await count(status="escalated"),
            "complaints_last_45_minutes":n,"surge_trigger_50_in_45m":n>=50}

@app.get("/api/admin/surge-check")
async def surge_check(request:Request,db:AsyncSession=Depends(get_db)):
    u,_=await auth(request,db)
    if u.role not in AUTHORITIES:raise HTTPException(403,"Authority access required")
    n=await count_last_45_minutes(db);return {"window_minutes":45,"complaints":n,"threshold":50,"triggered":n>=50}

async def import_users_core(items,db):
    created=updated=0
    for item in items:
        existing=(await db.execute(select(User).where(User.login_id==item.login_id))).scalar_one_or_none()
        if existing:
            existing.name=item.name;existing.role=item.role;existing.department=item.department;existing.designation=item.designation;existing.email=item.email;existing.phone=item.phone;existing.mentor_login_id=item.mentor_login_id;existing.source_system=item.source_system;existing.external_id=item.external_id;existing.active=item.active
            if item.password:existing.password_hash=hash_password(item.password)
            updated+=1
        else:
            if not item.password:raise HTTPException(400,f"Password required for new account {item.login_id}")
            db.add(User(login_id=item.login_id,name=item.name,role=item.role,password_hash=hash_password(item.password),department=item.department,designation=item.designation,email=item.email,phone=item.phone,mentor_login_id=item.mentor_login_id,source_system=item.source_system,external_id=item.external_id,active=item.active));created+=1
    await db.commit();return {"created":created,"updated":updated,"total_received":len(items)}

@app.post("/api/integration/users")
async def import_users(users:list[IntegratedUser],request:Request,db:AsyncSession=Depends(get_db)):
    u,_=await auth(request,db)
    if u.role!="administration":raise HTTPException(403,"Only Administration can import college identity data")
    if len(users)>10000:raise HTTPException(413,"Import batch too large")
    return await import_users_core(users,db)

@app.post("/api/integration/users/csv")
async def import_users_csv(file:UploadFile=File(...),request:Request=None,db:AsyncSession=Depends(get_db)):
    u,_=await auth(request,db)
    if u.role!="administration":raise HTTPException(403,"Only Administration can import identity data")
    if file.content_type not in {"text/csv","application/csv","application/vnd.ms-excel"}:raise HTTPException(400,"CSV file required")
    raw=await file.read()
    if len(raw)>5*1024*1024:raise HTTPException(413,"CSV exceeds 5 MB")
    try:rows=list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    except Exception:raise HTTPException(400,"Invalid CSV encoding")
    if len(rows)>10000:raise HTTPException(413,"CSV has too many rows")
    required={"login_id","name","role"}
    if not rows or not required.issubset(rows[0].keys()):raise HTTPException(400,"CSV must contain login_id,name,role columns")
    items=[]
    for r in rows:
        items.append(IntegratedUser(login_id=r["login_id"],name=r["name"],role=r["role"],password=r.get("password") or None,
            department=r.get("department"),designation=r.get("designation"),email=r.get("email"),phone=r.get("phone"),
            mentor_login_id=r.get("mentor_login_id") or None,source_system=r.get("source_system") or "college_erp",
            external_id=r.get("external_id") or None,active=(r.get("active","true").strip().lower()!="false")))
    return await import_users_core(items,db)

@app.get("/api/integration/schema")
async def integration_schema(request:Request,db:AsyncSession=Depends(get_db)):
    u,_=await auth(request,db)
    if u.role!="administration":raise HTTPException(403,"Administration access required")
    return {"required":["login_id","name","role"],"optional":["password (new users)","department","designation","email","phone","mentor_login_id","source_system","external_id","active"],
            "student_login":"GR number + password","staff_login":"employee ID + password"}

def developer_guard(x_developer_key:str|None=Header(default=None)):
    if not settings.developer_mode:raise HTTPException(403,"Developer mode is disabled")
    if not x_developer_key or not hmac_compare(x_developer_key,settings.developer_key):raise HTTPException(401,"Invalid developer key")
    return True
def hmac_compare(a,b):
    import hmac;return hmac.compare_digest(a,b)

@app.get("/api/developer/status")
async def developer_status(_:bool=Depends(developer_guard)):
    return {"developer_mode":True,"version":app.version,"editable_settings":["escalation_days","max_audio_mb"]}

@app.patch("/api/developer/config")
async def developer_config(data:DeveloperConfig,_:bool=Depends(developer_guard)):
    if data.escalation_days is not None:settings.escalation_days=data.escalation_days
    if data.max_audio_mb is not None:settings.max_audio_mb=data.max_audio_mb
    return {"updated":True,"escalation_days":settings.escalation_days,"max_audio_mb":settings.max_audio_mb}

@app.post("/api/developer/users")
async def developer_user(item:IntegratedUser,_:bool=Depends(developer_guard),db:AsyncSession=Depends(get_db)):
    existing=(await db.execute(select(User).where(User.login_id==item.login_id))).scalar_one_or_none()
    if existing:
        existing.name=item.name;existing.role=item.role;existing.department=item.department;existing.designation=item.designation;existing.email=item.email;existing.phone=item.phone;existing.mentor_login_id=item.mentor_login_id;existing.source_system=item.source_system;existing.external_id=item.external_id;existing.active=item.active
        if item.password:existing.password_hash=hash_password(item.password)
        action="updated"
    else:
        if not item.password:raise HTTPException(400,"Password required for new developer-created user")
        db.add(User(login_id=item.login_id,name=item.name,role=item.role,password_hash=hash_password(item.password),department=item.department,designation=item.designation,email=item.email,phone=item.phone,mentor_login_id=item.mentor_login_id,source_system=item.source_system,external_id=item.external_id,active=item.active));action="created"
    await db.commit();return {"action":action,"login_id":item.login_id}
