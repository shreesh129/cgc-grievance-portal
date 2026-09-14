import base64, hashlib, hmac, json, secrets, time, re
from fastapi import HTTPException, Header
from .config import settings

ROLES = {"student","teacher","mentor","administration","hod","dean","managing_director","vice_chancellor"}
AUTHORITIES = ROLES - {"student","teacher"}
STAFF_ROLES = ROLES - {"student"}

def validate_password(password: str):
    if len(password) < 10:
        raise HTTPException(400, "Password must contain at least 10 characters")
    if len(password) > 128:
        raise HTTPException(400, "Password is too long")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise HTTPException(400, "Password must contain letters and numbers")

def hash_password(password: str) -> str:
    validate_password(password)
    salt = secrets.token_bytes(16)
    rounds = 310_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"pbkdf2_sha256${rounds}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"

def verify_password(password: str, encoded: str) -> bool:
    try:
        alg, rounds, salt_b64, digest_b64 = encoded.split("$", 3)
        if alg != "pbkdf2_sha256": return False
        salt = base64.urlsafe_b64decode(salt_b64.encode())
        expected = base64.urlsafe_b64decode(digest_b64.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False

def _b64(obj):
    return base64.urlsafe_b64encode(
        json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()
    ).rstrip(b"=").decode()

def create_token(user_id: str, role: str, name: str, token_type="access"):
    now = int(time.time())
    ttl = settings.token_expiry_minutes * 60 if token_type == "access" else settings.refresh_expiry_days * 86400
    header = {"alg":"HS256","typ":"JWT"}
    payload = {"sub":user_id,"role":role,"name":name,"iat":now,"exp":now+ttl,
               "jti":secrets.token_urlsafe(18),"typ":token_type}
    a,b = _b64(header), _b64(payload)
    sig = hmac.new(settings.jwt_secret.encode(), f"{a}.{b}".encode(), hashlib.sha256).digest()
    return f"{a}.{b}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode()}"

def decode_token(token: str):
    try:
        a,b,s = token.split(".")
        raw = base64.urlsafe_b64decode((s + "===").encode())
        expected = hmac.new(settings.jwt_secret.encode(), f"{a}.{b}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(raw, expected): raise ValueError()
        payload = json.loads(base64.urlsafe_b64decode((b + "===").encode()))
        if payload.get("typ") != "access": raise ValueError()
        if int(payload["exp"]) <= int(time.time()): raise ValueError()
        return payload
    except Exception:
        raise HTTPException(401, "Invalid or expired authentication token")

def bearer(authorization: str | None):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Authentication required")
    token = authorization.split(" ",1)[1].strip()
    if not token or len(token) > 4096:
        raise HTTPException(401, "Invalid authentication token")
    return decode_token(token)

def require_roles(*allowed):
    def dependency(authorization: str | None = Header(default=None)):
        p = bearer(authorization)
        if p.get("role") not in allowed:
            raise HTTPException(403, "You are not authorized for this operation")
        return p
    return dependency

def validate_login_identity(role: str, login_id: str, anonymous: bool):
    role = role.lower().strip()
    if role not in ROLES: raise HTTPException(400, "Unsupported role")
    if not login_id.strip(): raise HTTPException(400, "Login ID is required")
    if anonymous and role not in {"student","teacher"}:
        raise HTTPException(403, "Only students and teachers may submit anonymously")
