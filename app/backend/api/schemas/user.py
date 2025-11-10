# app/backend/api/schemas/user.py
from pydantic import BaseModel,ConfigDict
from typing import Optional, List, Dict, Any

class LoginRequest(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserResponse(BaseModel):
    user_school_number: str
    user_full_name: str
    role: str

    model_config = ConfigDict(from_attributes=True)


class LoginResponse(BaseModel):
    """ The comprehensive login response. Schedule is optional. """
    token: Token
    user: UserResponse
    schedule: Optional[List[Dict[str, Any]]] = None # <-- MADE OPTIONAL

# Internal representation of JWT data
class TokenData(BaseModel):
    user_school_number: Optional[str] = None
    role: Optional[str] = None