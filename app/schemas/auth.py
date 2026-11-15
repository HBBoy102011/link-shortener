"""Authentication request and response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.config import settings


class RegisterRequest(BaseModel):
    """Payload for creating an account."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"email": "mushroom@example.com", "password": "quiet-forest-42"}]
        }
    )

    email: EmailStr = Field(description="Unique e-mail address.")
    password: str = Field(
        min_length=settings.password_min_length,
        max_length=settings.password_max_length,
        description="Plain password; only its bcrypt hash is stored.",
    )


class LoginRequest(BaseModel):
    """Payload for exchanging credentials for a JWT."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"email": "mushroom@example.com", "password": "quiet-forest-42"}]
        }
    )

    email: EmailStr
    password: str = Field(min_length=1, max_length=settings.password_max_length)


class UserResponse(BaseModel):
    """Public account information."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    created_at: datetime


class AuthResponse(BaseModel):
    """Token pair returned by registration and login."""

    access_token: str
    token_type: str = Field(default="bearer", examples=["bearer"])
    expires_in: int = Field(description="Token lifetime in seconds.")
    user: UserResponse
