from fastapi import APIRouter, HTTPException, Depends, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, validator
from typing import Optional, List
from datetime import datetime, timedelta
import asyncpg
import logging
import os
import bcrypt
import jwt
import re
from uuid import UUID

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer()

DATABASE_URL = os.getenv("DATABASE_URL")
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24 * 7  # 7 days
JWT_EXPIRATION_HOURS_ANONYMOUS = 24 * 30  # 30 days for anonymous users — matches cleanup window
# iOS app identity constants — for /auth/anonymous abuse protection
IOS_BUNDLE_ID = "com.remi.TuJe"
IOS_CLIENT_PLATFORM = "ios"

# Ordered onboarding phase lifecycle — index determines valid transitions.
# advance-onboarding-phase allows: to_phase == current (no-op) OR to_phase == current + 1.
ONBOARDING_PHASES = [
    "not_started",
    "account_checked",
    "home_first_view",
    "cta_tapped",
    "goal_selected",
    "level_selected",
    "mic_authorized",
    "disclaimer_confirmed",
    "initial_session_started",
    "initial_session_completed",
    "feedback_acknowledged",
    "account_creation_started",
    "account_credentials_entered",
    "expected_level_selected",      # 13  (was: account_verified — REPURPOSED)
    "last_french_usage_selected",   # 14  (NEW)
    "native_language_selected",     # 15  (NEW)
    "importance_level_selected",    # 16  (NEW)
    "languages_count_selected",     # 17  (NEW)
    "age_bracket_selected",         # 18  (NEW)
    "user_source_selected",         # 19  (NEW)
    "daily_commitment_selected",    # 20  (NEW)
    "tier_intro_shown",             # 21  (NEW — semantically replaces account_verified)
    "plan_tier_selected",           # 22  (existing, moved from 14)
    "payment_stub_acknowledged",    # 23  (NEW)
    "onboarding_completed",         # 24  (existing, terminal, moved from 15)
]

# Explicit whitelist of allowed backward phase transitions.
# revert-onboarding-phase only permits these (current_phase, to_phase) pairs.
ALLOWED_REVERTS = {
    ("goal_selected", "cta_tapped"),
    ("level_selected", "goal_selected"),
}

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


class OnboardingPrefsRequest(BaseModel):
    """Payload for the 2-question onboarding form."""
    goal_id: str
    initial_level_bucket: int  # 0, 1, or 2

    @validator('initial_level_bucket')
    def validate_bucket(cls, v):
        if v not in (0, 1, 2):
            raise ValueError('initial_level_bucket must be 0, 1, or 2')
        return v


class AdvanceOnboardingPhaseRequest(BaseModel):
    """Payload for POST /users/me/advance-onboarding-phase."""
    to_phase: str


class OnboardingPrefsGoalRequest(BaseModel):
    """Payload for POST /users/me/onboarding-prefs/goal (goal-only submit)."""
    goal_id: str


class RevertOnboardingPhaseRequest(BaseModel):
    """Payload for POST /users/me/revert-onboarding-phase."""
    to_phase: str


class UserProfile(BaseModel):
    id: UUID
    email: Optional[str]  # Now optional — anonymous users have no email
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
    initial_level_bucket: Optional[int] = None
    interest_ids: List[str]
    current_streak_days: int
    longest_streak_days: int
    total_sessions_completed: int
    total_interactions_completed: int
    subscription_tier: str  # 'free', 'basic', or 'pro'
    subscription_status: str  # 'never_subscribed', 'active', 'grace_period', 'expired'
    is_anonymous: bool
    onboarding_phase: str  # 'not_started', 'phase_1_in_progress', etc.
    created_at: datetime


class UpgradeAnonymousRequest(BaseModel):
    """Payload for upgrading an anonymous user to a permanent account."""
    email: EmailStr
    password: str
    username: str


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


def validate_password_strength(password: str) -> Optional[str]:
    """Validate password meets minimum security requirements.

    Returns None if valid, or an error message string if invalid.
    Rules: 8+ characters, at least 1 letter, at least 1 number.
    """
    if len(password) < 8:
        return "Password must be at least 8 characters long"

    has_letter = any(c.isalpha() for c in password)
    has_number = any(c.isdigit() for c in password)

    if not has_letter:
        return "Password must contain at least one letter"
    if not has_number:
        return "Password must contain at least one number"

    return None


def validate_username(username: str) -> Optional[str]:
    """Validate username format.

    Returns None if valid, or an error message string if invalid.
    Rules: 3-30 characters, alphanumeric + underscore + hyphen only.
    """
    if len(username) < 3:
        return "Username must be at least 3 characters long"
    if len(username) > 30:
        return "Username must be 30 characters or fewer"
    if not re.match(r'^[a-zA-Z0-9_-]+$', username):
        return "Username can only contain letters, numbers, underscores, and hyphens"

    return None
    

def create_access_token(user_id: str, email: Optional[str], expiration_hours: Optional[int] = None) -> str:
    """Create JWT access token.

    Args:
        user_id: UUID of the user (as string)
        email: User's email, or None for anonymous users
        expiration_hours: Optional override for token expiration. Defaults to JWT_EXPIRATION_HOURS.
    """
    if expiration_hours is None:
        expiration_hours = JWT_EXPIRATION_HOURS

    expiration = datetime.utcnow() + timedelta(hours=expiration_hours)
    payload = {
        "user_id": user_id,
        "email": email,  # may be None for anonymous users
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


async def verify_ios_app_headers(
    x_app_version: Optional[str] = Header(None, alias="X-App-Version"),
    x_bundle_id: Optional[str] = Header(None, alias="X-Bundle-ID"),
    x_client_platform: Optional[str] = Header(None, alias="X-Client-Platform"),
) -> dict:
    """Verify request comes from the iOS app.

    This is a speed bump against casual abuse, not a fortress.
    A motivated attacker can sniff these headers from real requests.
    Long-term solution: Apple App Attest framework (v1.1+).
    """
    # All three headers must be present
    if not x_app_version or not x_bundle_id or not x_client_platform:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required client headers"
        )

    # Bundle ID must match exactly
    if x_bundle_id != IOS_BUNDLE_ID:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid client identifier"
        )

    # Platform must be iOS (for now — add 'android' here when you ship Android)
    if x_client_platform != IOS_CLIENT_PLATFORM:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unsupported client platform"
        )

    # Return headers as dict for potential use in endpoints
    return {
        "app_version": x_app_version,
        "bundle_id": x_bundle_id,
        "client_platform": x_client_platform,
    }

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
            RETURNING id, email, username, display_name, level, role,
                      goal_id, initial_level_bucket, created_at
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
                "goal_id": user["goal_id"],
                "initial_level_bucket": user["initial_level_bucket"],
                "created_at": user["created_at"]
            }
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/auth/anonymous")
async def create_anonymous_user(
    client_headers: dict = Depends(verify_ios_app_headers),
):
    """Create an anonymous user for app onboarding.

    Called by iOS on first launch when no JWT exists in Keychain.
    Returns a JWT (30-day expiration) that the app uses for all subsequent
    requests until the user upgrades to a permanent account.

    The same user_id is preserved on upgrade — all session data follows.
    """
    try:
        conn = await asyncpg.connect(DATABASE_URL)

        # Create anonymous user row
        # - id auto-generated by gen_random_uuid()
        # - is_anonymous=true, anonymous_created_at=now (set explicitly for clarity)
        # - email, username, password_hash all NULL
        # - subscription_tier defaults to 'free'
        # - onboarding_phase set to 'not_started' (user hasn't done anything yet)
        new_user = await conn.fetchrow("""
            INSERT INTO brain_user (
                auth_provider,
                is_anonymous,
                anonymous_created_at,
                onboarding_phase
            )
            VALUES ('anonymous', true, NOW(), 'not_started')
            RETURNING id, email, username, display_name, level, role,
                      is_anonymous, subscription_tier, onboarding_phase,
                      goal_id, initial_level_bucket, created_at
        """)

        await conn.close()

        # Create JWT with 30-day expiration
        access_token = create_access_token(
            user_id=str(new_user["id"]),
            email=None,  # anonymous users have no email
            expiration_hours=JWT_EXPIRATION_HOURS_ANONYMOUS
        )

        return {
            "message": "Anonymous user created",
            "access_token": access_token,
            "token_type": "bearer",
            "is_new_user": True,
            "user": {
                "id": str(new_user["id"]),
                "email": new_user["email"],  # will be None
                "username": new_user["username"],  # will be None
                "display_name": new_user["display_name"],  # will be None
                "level": new_user["level"],
                "cefr_level": level_to_cefr(new_user["level"]),
                "role": new_user["role"],
                "is_anonymous": new_user["is_anonymous"],
                "subscription_tier": new_user["subscription_tier"],
                "onboarding_phase": new_user["onboarding_phase"],
                "goal_id": new_user["goal_id"],
                "initial_level_bucket": new_user["initial_level_bucket"],
                "created_at": new_user["created_at"]
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create anonymous user: {str(e)}"
        )


@router.post("/auth/upgrade-anonymous")
async def upgrade_anonymous_user(
    upgrade_data: UpgradeAnonymousRequest,
    current_user: dict = Depends(get_current_user),
):
    """Convert an anonymous user to a permanent account, preserving user_id.

    Called by iOS during Phase 2 of onboarding when the user fills out
    the account creation form. The same brain_user row is updated in place —
    all session data and behavior signals automatically belong to the new account.

    Requires:
    - Caller must be authenticated as an anonymous user (is_anonymous=true)
    - Email must not already be taken by another user
    - Password must meet strength requirements
    - Username must meet format requirements
    """
    # Validate caller is actually anonymous
    if not current_user.get("is_anonymous"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account is already a permanent account"
        )

    # Validate password strength
    password_error = validate_password_strength(upgrade_data.password)
    if password_error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=password_error
        )

    # Validate username format
    username_error = validate_username(upgrade_data.username)
    if username_error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=username_error
        )

    # Normalize email (lowercase, strip whitespace)
    email_normalized = upgrade_data.email.lower().strip()
    username_normalized = upgrade_data.username.strip()

    try:
        conn = await asyncpg.connect(DATABASE_URL)

        # Check email is not already in use by ANOTHER user
        existing_email = await conn.fetchrow(
            "SELECT id FROM brain_user WHERE LOWER(email) = $1 AND id != $2",
            email_normalized,
            current_user["id"]
        )
        if existing_email:
            await conn.close()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This email is already registered. Please log in instead."
            )

        # Check username is not already in use by ANOTHER user
        existing_username = await conn.fetchrow(
            "SELECT id FROM brain_user WHERE LOWER(username) = LOWER($1) AND id != $2",
            username_normalized,
            current_user["id"]
        )
        if existing_username:
            await conn.close()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This username is already taken. Please choose another."
            )

        # Hash the password
        password_hash = hash_password(upgrade_data.password)

        # Update the existing brain_user row in place
        # - Preserves user_id (critical for data continuity)
        # - Switches is_anonymous to false
        # - Sets account_created_at = NOW() (drives 14-day interstitial suppression)
        # - Switches auth_provider from 'anonymous' to 'email'
        # - Advances onboarding_phase to 'account_credentials_entered'
        # - Sets display_name to username by default (user can change later)
        updated_user = await conn.fetchrow("""
            UPDATE brain_user
            SET email = $1,
                username = $2,
                display_name = $2,
                password_hash = $3,
                is_anonymous = false,
                account_created_at = NOW(),
                auth_provider = 'email',
                onboarding_phase = 'account_credentials_entered',
                updated_at = NOW()
            WHERE id = $4
            RETURNING id, email, username, display_name, level, role,
                      is_anonymous, subscription_tier, subscription_status,
                      onboarding_phase, is_email_verified,
                      goal_id, initial_level_bucket, created_at, account_created_at
        """, email_normalized, username_normalized, password_hash, current_user["id"])

        await conn.close()

        # TODO (Phase A.5): Send verification email via magic link
        # send_verification_email(email_normalized, str(updated_user["id"]))
        # For now, is_email_verified stays false; user can still use the app.

        # Issue a new JWT with regular (7-day) expiration since user is no longer anonymous
        new_access_token = create_access_token(
            user_id=str(updated_user["id"]),
            email=updated_user["email"],
            # expiration_hours omitted → defaults to JWT_EXPIRATION_HOURS (7 days)
        )

        return {
            "message": "Account created successfully",
            "access_token": new_access_token,
            "token_type": "bearer",
            "is_new_user": False,  # not "new" — they existed as anonymous
            "user": {
                "id": str(updated_user["id"]),
                "email": updated_user["email"],
                "username": updated_user["username"],
                "display_name": updated_user["display_name"],
                "level": updated_user["level"],
                "cefr_level": level_to_cefr(updated_user["level"]),
                "role": updated_user["role"],
                "is_anonymous": updated_user["is_anonymous"],
                "subscription_tier": updated_user["subscription_tier"],
                "subscription_status": updated_user["subscription_status"],
                "onboarding_phase": updated_user["onboarding_phase"],
                "is_email_verified": updated_user["is_email_verified"],
                "goal_id": updated_user["goal_id"],
                "initial_level_bucket": updated_user["initial_level_bucket"],
                "created_at": updated_user["created_at"],
                "account_created_at": updated_user["account_created_at"],
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upgrade account: {str(e)}"
        )


@router.post("/auth/login")
async def login(credentials: UserLogin):
    """Login with email and password"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        # Get user by email
        user = await conn.fetchrow("""
            SELECT id, email, password_hash, username, display_name, level, role,
                   is_active, goal_id, initial_level_bucket
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
                "role": user["role"],
                "goal_id": user["goal_id"],
                "initial_level_bucket": user["initial_level_bucket"],
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
            SELECT id, email, username, display_name, level, role,
                   is_active, goal_id, initial_level_bucket
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
                    "role": user["role"],
                    "goal_id": user["goal_id"],
                    "initial_level_bucket": user["initial_level_bucket"],
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
                RETURNING id, email, username, display_name, level, role,
                          goal_id, initial_level_bucket, created_at
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
                    "goal_id": new_user["goal_id"],
                    "initial_level_bucket": new_user["initial_level_bucket"],
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
        initial_level_bucket=current_user["initial_level_bucket"],
        interest_ids=current_user["interest_ids"] or [],
        current_streak_days=current_user["current_streak_days"],
        longest_streak_days=current_user["longest_streak_days"],
        total_sessions_completed=current_user["total_sessions_completed"],
        total_interactions_completed=current_user["total_interactions_completed"],
        subscription_tier=current_user.get("subscription_tier", "free"),
        subscription_status=current_user.get("subscription_status", "never_subscribed"),
        is_anonymous=current_user.get("is_anonymous", False),
        onboarding_phase=current_user.get("onboarding_phase", "not_started"),
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


@router.post("/users/me/onboarding-prefs")
async def submit_onboarding_prefs(
    prefs: OnboardingPrefsRequest,
    current_user: dict = Depends(get_current_user)
):
    """Submit the 2-question onboarding form answers.

    Writes goal_id and initial_level_bucket to brain_user, and advances
    onboarding_phase from 'not_started' to 'phase_1_in_progress' if needed.

    Idempotent — calling this multiple times overwrites previous answers.
    """
    try:
        conn = await asyncpg.connect(DATABASE_URL)

        # Verify the goal exists in brain_user_goal.
        # fetchval returns 1 if found, None if no row matches.
        goal_exists = await conn.fetchval(
            "SELECT 1 FROM brain_user_goal WHERE id = $1",
            prefs.goal_id
        )
        if goal_exists is None:
            await conn.close()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid goal_id — no matching live goal found"
            )

        # Update brain_user. Advance onboarding_phase to 'level_selected' (the user
        # just answered both goal + level questions). Don't move backward — if the
        # user is already past level_selected (e.g. re-submitting prefs mid-session),
        # leave the phase unchanged.
        # NOTE: This guard allows forward-skip (e.g., not_started → level_selected
        # in one form submit). This is intentional for the current single-screen form
        # (D17). When the form is split into two screens (D19, M4 part 2 iOS work),
        # change `<` to `== target_idx - 1` for strict one-step.
        # RETURNING onboarding_phase so the iOS client can update its local state
        # without a separate /users/me round-trip.
        current_phase = current_user.get("onboarding_phase", "not_started")
        target_phase = "level_selected"
        user_id = str(current_user["id"])

        if current_phase not in ONBOARDING_PHASES:
            logger.error(f"❌ Corrupt onboarding_phase '{current_phase}' for user {user_id}; skipping phase update")
            new_phase = current_phase
        elif ONBOARDING_PHASES.index(current_phase) < ONBOARDING_PHASES.index(target_phase):
            new_phase = target_phase
        else:
            new_phase = current_phase

        updated = await conn.fetchrow("""
            UPDATE brain_user
            SET goal_id = $1,
                initial_level_bucket = $2,
                onboarding_phase = $3,
                updated_at = NOW()
            WHERE id = $4
            RETURNING onboarding_phase
        """, prefs.goal_id, prefs.initial_level_bucket, new_phase, current_user["id"])

        await conn.close()

        return {
            "message": "Onboarding preferences saved",
            "goal_id": prefs.goal_id,
            "initial_level_bucket": prefs.initial_level_bucket,
            "onboarding_phase": updated["onboarding_phase"],
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save onboarding preferences: {str(e)}"
        )


@router.post("/users/me/onboarding-prefs/goal")
async def submit_onboarding_goal(
    prefs: OnboardingPrefsGoalRequest,
    current_user: dict = Depends(get_current_user),
):
    """Submit the goal selection (first of two split onboarding questions).

    Writes goal_id to brain_user and advances onboarding_phase to 'goal_selected'
    if the user is not already at or past that phase.
    """
    user_id = str(current_user["id"])

    if not prefs.goal_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="goal_id must not be empty",
        )

    try:
        conn = await asyncpg.connect(DATABASE_URL)

        # Verify the goal exists in brain_user_goal.
        goal_exists = await conn.fetchval(
            "SELECT 1 FROM brain_user_goal WHERE id = $1",
            prefs.goal_id,
        )
        if goal_exists is None:
            await conn.close()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid goal_id — no matching goal found",
            )

        # Save goal_id and conditionally advance phase.
        # NOTE: This guard allows forward-skip (e.g., not_started → goal_selected
        # in one call). This is intentional for the current single-screen form
        # (D17). When the form is split into two screens (D19, M4 part 2 iOS work),
        # change `<` to `== target_idx - 1` for strict one-step.
        current_phase = current_user.get("onboarding_phase", "not_started")
        target_phase = "goal_selected"

        if current_phase not in ONBOARDING_PHASES:
            logger.error(f"❌ Corrupt onboarding_phase '{current_phase}' for user {user_id}; skipping phase update")
            new_phase = current_phase
        elif ONBOARDING_PHASES.index(current_phase) < ONBOARDING_PHASES.index(target_phase):
            new_phase = target_phase
        else:
            new_phase = current_phase

        updated = await conn.fetchrow("""
            UPDATE brain_user
            SET goal_id = $1,
                onboarding_phase = $2,
                updated_at = NOW()
            WHERE id = $3
            RETURNING onboarding_phase
        """, prefs.goal_id, new_phase, current_user["id"])

        await conn.close()

        logger.info(
            f"✅ Goal saved for user {user_id}: goal_id={prefs.goal_id}, "
            f"phase: '{current_phase}' → '{updated['onboarding_phase']}'"
        )

        return {
            "success": True,
            "goal_id": prefs.goal_id,
            "onboarding_phase": updated["onboarding_phase"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to save goal for user {user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save goal: {str(e)}",
        )


@router.post("/users/me/advance-onboarding-phase")
async def advance_onboarding_phase(
    request: AdvanceOnboardingPhaseRequest,
    current_user: dict = Depends(get_current_user),
):
    """Advance the user's onboarding phase by exactly one step.

    Strict forward-only validation:
    - to_phase == current phase  → 200 no-op (idempotent)
    - to_phase == current + 1    → advance + 200
    - anything else              → 400 invalid_transition
    """
    user_id = str(current_user["id"])
    current_phase = current_user.get("onboarding_phase", "not_started")
    to_phase = request.to_phase

    # Validate current phase is in the lifecycle (corrupt state if not)
    try:
        current_index = ONBOARDING_PHASES.index(current_phase)
    except ValueError:
        logger.error(
            f"❌ Corrupt onboarding_phase '{current_phase}' for user {user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Corrupt onboarding_phase: '{current_phase}' is not a recognized phase",
        )

    # Validate requested phase exists
    try:
        to_index = ONBOARDING_PHASES.index(to_phase)
    except ValueError:
        logger.warning(
            f"⚠️ Invalid phase '{to_phase}' requested by user {user_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error": "invalid_phase",
                "detail": f"'{to_phase}' is not a recognized onboarding phase",
            },
        )

    # No-op: already at the requested phase
    if to_index == current_index:
        logger.info(
            f"🔄 No-op phase advance for user {user_id}: already at '{current_phase}'"
        )
        return {"success": True, "phase": to_phase, "changed": False}

    # Valid advance: exactly one step forward
    if to_index == current_index + 1:
        try:
            conn = await asyncpg.connect(DATABASE_URL)
            await conn.execute(
                """
                UPDATE brain_user
                SET onboarding_phase = $1, updated_at = NOW()
                WHERE id = $2
                """,
                to_phase,
                current_user["id"],
            )
            await conn.close()

            logger.info(
                f"✅ Phase advanced for user {user_id}: '{current_phase}' → '{to_phase}'"
            )
            return {"success": True, "phase": to_phase, "changed": True}

        except Exception as e:
            logger.error(
                f"❌ Failed to advance phase for user {user_id}: {e}"
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to advance onboarding phase: {str(e)}",
            )

    # Invalid transition: skip or backward
    next_phase = ONBOARDING_PHASES[current_index + 1] if current_index + 1 < len(ONBOARDING_PHASES) else None
    allowed = f"'{current_phase}' (no-op)"
    if next_phase:
        allowed += f" or '{next_phase}'"

    logger.warning(
        f"⚠️ Invalid transition for user {user_id}: "
        f"'{current_phase}' → '{to_phase}' (allowed: {allowed})"
    )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "success": False,
            "error": "invalid_transition",
            "detail": (
                f"Cannot transition from '{current_phase}' to '{to_phase}'. "
                f"Allowed: {allowed}."
            ),
        },
    )


@router.post("/users/me/revert-onboarding-phase")
async def revert_onboarding_phase(
    request: RevertOnboardingPhaseRequest,
    current_user: dict = Depends(get_current_user),
):
    """Revert the user's onboarding phase to a previous step.

    Only explicitly whitelisted (current_phase, to_phase) pairs are allowed.
    All other transitions are rejected with 400 invalid_revert.
    """
    user_id = str(current_user["id"])
    current_phase = current_user.get("onboarding_phase", "not_started")
    to_phase = request.to_phase

    # Check against the explicit whitelist
    if (current_phase, to_phase) not in ALLOWED_REVERTS:
        # Build a helpful error message
        allowed_from_current = [
            target for source, target in ALLOWED_REVERTS if source == current_phase
        ]
        if allowed_from_current:
            detail = (
                f"Cannot revert from '{current_phase}' to '{to_phase}'. "
                f"Allowed revert(s) from '{current_phase}': {allowed_from_current}."
            )
        else:
            detail = f"No reverts are allowed from '{current_phase}'."

        logger.warning(
            f"⚠️ Invalid revert for user {user_id}: "
            f"'{current_phase}' → '{to_phase}'"
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "success": False,
                "error": "invalid_revert",
                "detail": detail,
            },
        )

    # Valid revert — update the phase
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute(
            """
            UPDATE brain_user
            SET onboarding_phase = $1, updated_at = NOW()
            WHERE id = $2
            """,
            to_phase,
            current_user["id"],
        )
        await conn.close()

        logger.info(
            f"✅ Phase reverted for user {user_id}: '{current_phase}' → '{to_phase}'"
        )
        return {"success": True, "phase": to_phase, "changed": True}

    except Exception as e:
        logger.error(
            f"❌ Failed to revert phase for user {user_id}: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to revert onboarding phase: {str(e)}",
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

@router.get("/users/{user_id}/role")
async def get_user_role_by_id(user_id: str):
    """Get user's role by user ID - for static API key authentication"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        user = await conn.fetchrow("""
            SELECT id, email, username, role, is_active
            FROM brain_user
            WHERE id = $1 AND is_active = true AND deleted_at IS NULL
        """, user_id)
        
        await conn.close()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found or inactive"
            )
        
        return {
            "user_id": str(user["id"]),
            "email": user["email"],
            "username": user["username"],
            "role": user["role"],
            "is_admin": user["role"] == "admin",
            "can_access_test": user["role"] in ["admin", "super_admin"]
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

# Alternative: Simple role check endpoint
@router.get("/admin/check-access/{user_id}")
async def check_admin_access(user_id: str):
    """Simple admin access check"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        is_admin = await conn.fetchval("""
            SELECT role = 'admin' as is_admin
            FROM brain_user
            WHERE id = $1 AND is_active = true AND deleted_at IS NULL
        """, user_id)
        
        await conn.close()
        
        return {
            "user_id": user_id,
            "has_admin_access": bool(is_admin),
            "can_access_test_section": bool(is_admin)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.get("/users/{user_id}/role")
async def get_user_role_by_id(user_id: str):
    """Get user's role by user ID - for section_test admin access control"""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        
        user = await conn.fetchrow("""
            SELECT id, email, username, role, is_active
            FROM brain_user
            WHERE id = $1 AND is_active = true AND deleted_at IS NULL
        """, user_id)
        
        await conn.close()
        
        if not user:
            return {
                "user_found": False,
                "requires_login": True,
                "message": "User not found or inactive"
            }
        
        return {
            "user_found": True,
            "requires_login": False,
            "user_id": str(user["id"]),
            "email": user["email"],
            "username": user["username"],
            "role": user["role"],
            "is_admin": user["role"] == "admin",
            "can_access_test": user["role"] in ["admin", "super_admin"]
        }
        
    except Exception as e:
        return {
            "user_found": False,
            "requires_login": True,
            "error": str(e),
            "message": "Authentication required"
        }
