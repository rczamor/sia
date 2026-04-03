from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings
from app.models.schemas import LoginRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


def create_token(email: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expiry_hours)
    return jwt.encode({"sub": email, "exp": expires}, settings.jwt_secret, algorithm=ALGORITHM)


def verify_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        email: str = payload.get("sub", "")
        if not email:
            raise HTTPException(status_code=401, detail="Invalid token")
        return email
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return verify_token(credentials.credentials)


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    if request.email != settings.admin_email:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not settings.admin_password_hash:
        raise HTTPException(status_code=500, detail="Admin password not configured")
    if not pwd_context.verify(request.password, settings.admin_password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(request.email)
    return TokenResponse(access_token=token)
