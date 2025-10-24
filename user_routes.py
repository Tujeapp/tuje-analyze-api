from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, validator
from typing import Optional, List
from datetime import datetime, timedelta
import asyncpg
import os
import bcrypt
import jwt
from uuid import UUID

router = APIRouter()
security = HTTPBearer()

DATABASE_URL = os.getenv("DATABASE_URL")
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24 * 7  # 7 days

if not DATABASE_URL:
    raise RuntimeError("Missing required environment variable: DATABASE_URL")


# ========================================
# Pydantic Models
# ========================================

class UserRegistration(BaseModel):
    email: EmailStr
    password: str
    username: Optional[str] = None
    display_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    native_language: str = "en"
    target_language: str = "fr"
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters long')
        return v
    
    @validator('username')
    def validate_username(cls, v):
        if v is not None:
            if len(v) < 3:
                raise ValueError('Username must be at least 3 characters long')
            if not v.replace('_', '').replace('-', '').isalnum():
                raise ValueError('Username can only contain letters, numbers, hyphens, and underscores')
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class SocialAuthLogin(BaseModel):
    auth_provider: str  # 'google', 'apple', 'facebook'
    auth_provider_id: str
    email: EmailStr
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    
    @validator('auth_provider')
    def validate_provider(cls, v):
        allowed_providers = ['google', 'apple', 'facebook']
        if v.lower() not in allowed_providers:
            raise ValueError(f'Auth provider must be one of: {", ".join(allowed_providers)}')
        return v.lower()


class UserProfile(BaseModel):
    id: UUID
    email: str
    username: Optional[str]
    display_name: Optional[str]
    first_name: Optional[str]
    last_name: Optional[str]
    avatar_url: Optional[str]
    bio: Optional[str]
    level: int
    cefr_level: str  # Computed from level
    role: str
    goal_id: Optional[str]
    interest_ids: List[str]
    current_streak_days: int
    longest_streak_days: int
    total_sessions_completed: int
    total_interactions_completed: int
    is_premium: bool
    subscription_status: str
    created_at: datetime


class UserUpdate(BaseModel):
    username: Optional[str] = None
    display_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    goal_id: Optional[str] = None
    interest_ids: Optional[List[str]] = None
    preferred_session_mood: Optional[str] = None
    preferred_session_duration_minutes: Optional[int] = None
    native_language: Optional[str] = None
    target_language: Optional[str] = None
    ui_language: Optional[str] = None
    timezone: Optional[str] = None


# ========================================
# Helper Functions
# ========================================

def hash_password(password: str) -> str:
    """Hash password using bcrypt"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    """Verify password against hash"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


def create_access_token(user_id: str, email: str) -> str:
    """Create JWT access token"""
    expiration = datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS)
    payload = {
        "user_id": user_id,
        "email": email,
        "exp": expiration
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token


def decode_access_token(token: str) -> dict:
    """Decode and validate JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )


def level_to_cefr(level: int) -> str:
    """Convert numeric level (0-500) to CEFR level"""
    if level < 50:
        return "A0.0"
    elif level < 100:
        return "A0.1"
    elif level < 150:
        return "A1.0"
    elif level < 200:
        return "A1.1"
    elif level < 250:
        return "A2.0"
    elif level < 300:
        return "A2.1"
    elif level < 350:
        return "B1.0"
    elif level < 400:
        return "B1.1"
    elif level < 450:
        return "B2.0"
    elif level < 500:
        return "B2.1"
    else:
        return "C1.0"


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Dependency to get current authenticated user"""
    token = credentials.credentials
    payload = decode_access_token(token)
    
    conn = await asyncpg.connect(DATABASE_URL)
    user = await conn.fetchrow("""
        SELECT * FROM brain_user 
        WHERE id = $1 AND is_active = true AND deleted_at IS NULL
    """, payload["user_id"])
    await conn.close()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )
    
    return dict(user)


# ========================================
# Authentication Endpoints
# ========================================

@router.post("/auth/register")
async def register(user_data: UserRegistration):
    """Register a new user"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Check if email already exists
        existing_email = await conn.fetchrow(
            "SELECT id FROM brain_user WHERE email = $1", 
            user_data.email
        )
        if existing_email:
            await conn.close()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        
        # Check if username already exists (if provided)
        if user_data.username:
            existing_username = await conn.fetchrow(
                "SELECT id FROM brain_user WHERE username = $1",
                user_data.username
            )
            if existing_username:
                await conn.close()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username already taken"
                )
        
        # Hash password
        password_hash = hash_password(user_data.password)
        
        # Create user
        user = await conn.fetchrow("""
            INSERT INTO brain_user (
                email, username, password_hash, display_name, 
                first_name, last_name, native_language, target_language,
                auth_provider
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'email')
            RETURNING id, email, username, display_name, level, role, created_at
        """, 
            user_data.email,
            user_data.username,
            password_hash,
            user_data.display_name,
            user_data.first_name,
            user_data.last_name,
            user_data.native_language,
            user_data.target_language
        )
        
        await conn.close()
        
        # Create access token
        access_token = create_access_token(str(user["id"]), user["email"])
        
        return {
            "message": "User registered successfully",
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": str(user["id"]),
                "email": user["email"],
                "username": user["username"],
                "display_name": user["display_name"],
                "level": user["level"],
                "cefr_level": level_to_cefr(user["level"]),
                "role": user["role"],
                "created_at": user["created_at"]
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/auth/login")
async def login(credentials: UserLogin):
    """Login with email and password"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Get user by email
        user = await conn.fetchrow("""
            SELECT id, email, password_hash, username, display_name, level, role, is_active
            FROM brain_user
            WHERE email = $1 AND deleted_at IS NULL
        """, credentials.email)
        
        await conn.close()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        if not user["is_active"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive"
            )
        
        # Verify password
        if not verify_password(credentials.password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        # Update last login
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("""
            UPDATE brain_user 
            SET last_login_at = NOW()
            WHERE id = $1
        """, user["id"])
        await conn.close()
        
        # Create access token
        access_token = create_access_token(str(user["id"]), user["email"])
        
        return {
            "message": "Login successful",
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": str(user["id"]),
                "email": user["email"],
                "username": user["username"],
                "display_name": user["display_name"],
                "level": user["level"],
                "cefr_level": level_to_cefr(user["level"]),
                "role": user["role"]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/auth/social")
async def social_auth(social_data: SocialAuthLogin):
    """Login or register with social auth (Google, Apple, Facebook)"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Check if user exists with this social auth
        user = await conn.fetchrow("""
            SELECT id, email, username, display_name, level, role, is_active
            FROM brain_user
            WHERE auth_provider = $1 AND auth_provider_id = $2 AND deleted_at IS NULL
        """, social_data.auth_provider, social_data.auth_provider_id)
        
        if user:
            # User exists - login
            if not user["is_active"]:
                await conn.close()
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Account is inactive"
                )
            
            # Update last login
            await conn.execute("""
                UPDATE brain_user 
                SET last_login_at = NOW()
                WHERE id = $1
            """, user["id"])
            
            await conn.close()
            
            access_token = create_access_token(str(user["id"]), user["email"])
            
            return {
                "message": "Login successful",
                "access_token": access_token,
                "token_type": "bearer",
                "is_new_user": False,
                "user": {
                    "id": str(user["id"]),
                    "email": user["email"],
                    "username": user["username"],
                    "display_name": user["display_name"],
                    "level": user["level"],
                    "cefr_level": level_to_cefr(user["level"]),
                    "role": user["role"]
                }
            }
        else:
            # New user - register
            # Check if email already exists with different auth
            existing_email = await conn.fetchrow(
                "SELECT id FROM brain_user WHERE email = $1",
                social_data.email
            )
            if existing_email:
                await conn.close()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already registered with different auth method"
                )
            
            # Create new user (no password needed for social auth)
            new_user = await conn.fetchrow("""
                INSERT INTO brain_user (
                    email, auth_provider, auth_provider_id, 
                    display_name, avatar_url, password_hash,
                    is_email_verified, email_verified_at
                )
                VALUES ($1, $2, $3, $4, $5, '', true, NOW())
                RETURNING id, email, username, display_name, level, role, created_at
            """,
                social_data.email,
                social_data.auth_provider,
                social_data.auth_provider_id,
                social_data.display_name,
                social_data.avatar_url
            )
            
            await conn.close()
            
            access_token = create_access_token(str(new_user["id"]), new_user["email"])
            
            return {
                "message": "User registered successfully",
                "access_token": access_token,
                "token_type": "bearer",
                "is_new_user": True,
                "user": {
                    "id": str(new_user["id"]),
                    "email": new_user["email"],
                    "username": new_user["username"],
                    "display_name": new_user["display_name"],
                    "level": new_user["level"],
                    "cefr_level": level_to_cefr(new_user["level"]),
                    "role": new_user["role"],
                    "created_at": new_user["created_at"]
                }
            }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


# ========================================
# User Profile Endpoints
# ========================================

@router.get("/users/me/role")
async def get_current_user_role(current_user: dict = Depends(get_current_user)):
    """Get current user's role for frontend authorization"""
    return {
        "user_id": current_user["id"],
        "email": current_user["email"],
        "role": current_user["role"],
        "is_admin": current_user["role"] == "admin",
        "can_access_test": current_user["role"] in ["admin", "super_admin"]
    }

@router.get("/users/me", response_model=UserProfile)
async def get_my_profile(current_user: dict = Depends(get_current_user)):
    """Get current user's profile"""
    return UserProfile(
        id=current_user["id"],
        email=current_user["email"],
        username=current_user["username"],
        display_name=current_user["display_name"],
        first_name=current_user["first_name"],
        last_name=current_user["last_name"],
        avatar_url=current_user["avatar_url"],
        bio=current_user["bio"],
        level=current_user["level"],
        cefr_level=level_to_cefr(current_user["level"]),
        role=current_user["role"],
        goal_id=current_user["goal_id"],
        interest_ids=current_user["interest_ids"] or [],
        current_streak_days=current_user["current_streak_days"],
        longest_streak_days=current_user["longest_streak_days"],
        total_sessions_completed=current_user["total_sessions_completed"],
        total_interactions_completed=current_user["total_interactions_completed"],
        is_premium=current_user["is_premium"],
        subscription_status=current_user["subscription_status"],
        created_at=current_user["created_at"]
    )


@router.patch("/users/me")
async def update_my_profile(
    updates: UserUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Update current user's profile"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Build dynamic update query
        update_fields = []
        params = []
        param_count = 1
        
        update_data = updates.dict(exclude_unset=True)
        
        for field, value in update_data.items():
            # Convert camelCase to snake_case for database
            db_field = ''.join(['_' + c.lower() if c.isupper() else c for c in field]).lstrip('_')
            update_fields.append(f"{db_field} = ${param_count}")
            params.append(value)
            param_count += 1
        
        if not update_fields:
            await conn.close()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update"
            )
        
        # Add user_id as last parameter
        params.append(current_user["id"])
        
        query = f"""
            UPDATE brain_user
            SET {', '.join(update_fields)}
            WHERE id = ${param_count}
            RETURNING id, email, username, display_name, level, role
        """
        
        updated_user = await conn.fetchrow(query, *params)
        await conn.close()
        
        return {
            "message": "Profile updated successfully",
            "user": {
                "id": str(updated_user["id"]),
                "email": updated_user["email"],
                "username": updated_user["username"],
                "display_name": updated_user["display_name"],
                "level": updated_user["level"],
                "cefr_level": level_to_cefr(updated_user["level"]),
                "role": updated_user["role"]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/users/{user_id}")
async def get_user_public_profile(user_id: UUID):
    """Get public profile of any user (limited info)"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        user = await conn.fetchrow("""
            SELECT 
                id, username, display_name, avatar_url, bio, level,
                current_streak_days, longest_streak_days,
                total_sessions_completed, total_interactions_completed,
                created_at
            FROM brain_user
            WHERE id = $1 AND is_active = true AND deleted_at IS NULL
        """, str(user_id))
        
        await conn.close()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return {
            "id": str(user["id"]),
            "username": user["username"],
            "display_name": user["display_name"],
            "avatar_url": user["avatar_url"],
            "bio": user["bio"],
            "level": user["level"],
            "cefr_level": level_to_cefr(user["level"]),
            "current_streak_days": user["current_streak_days"],
            "longest_streak_days": user["longest_streak_days"],
            "total_sessions_completed": user["total_sessions_completed"],
            "total_interactions_completed": user["total_interactions_completed"],
            "member_since": user["created_at"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
