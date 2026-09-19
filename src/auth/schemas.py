from pydantic import BaseModel, Field
from typing import Optional

class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    theme: Optional[str] = None
    current_password: Optional[str] = None
    password: Optional[str] = Field(None, min_length=8)


class EmailRateLimitRequest(BaseModel):
    email: str
    action: str  # 'email_verification', 'forgot_password', or 'change_password_confirmation'


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: str
    password: str


