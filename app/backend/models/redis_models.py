from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from uuid import UUID
from .db_models import User  # Importing the User model from our db_models

class UserSessionRedis(BaseModel):
    """
    Represents a user's session data stored in Redis.
    """
    user_data: User = Field(..., description="The core user data from the database.")
    session_id: UUID = Field(..., description="Unique ID for this specific session.")
    session_start_time: datetime = Field(..., description="The time this session began.")
    session_end_time: datetime = Field(..., description="The time this session will expire.")
    image_url: Optional[str] = None

# --- REFACTORED MODELS ---

class AttendanceRedis(BaseModel):
    """
    Represents an active attendance session in Redis, serving as the single source of truth.
    This model combines discoverability (teacher_full_name) with the full session data.
    """
    # Fields from db_models.Attendance
    attendance_id: UUID = Field(..., description="Unique identifier for the attendance session")
    teacher_school_number: str = Field(..., description="FK linking to the teacher who started the session")
    teacher_full_name: str = Field(..., description="Full name of the teacher for easy identification and cron job processing.")
    lesson_name: str
    ip_address: Optional[str] = None
    start_time: datetime
    end_time: datetime
    security_option: int
    is_deleted: bool = False
    deletion_reason: Optional[str] = None
    deletion_time: Optional[datetime] = None


class AttendanceRecordRedis(BaseModel):
    """
    Represents a single student's attendance record for an active session in Redis.
    It includes all database fields plus the student's full name to ensure the cron job
    has all necessary data to create a User record if one doesn't exist.
    """
    # Required fields
    attendance_id: UUID = Field(..., description="FK linking to the specific attendance session")
    student_number: str = Field(..., description="FK linking to the student")
    student_full_name: str = Field(..., description="The student's full name to prevent data integrity issues.")

    # Optional fields with default values, matching the style in db_models.py
    is_attended: bool = False
    attendance_time: Optional[datetime] = None
    fail_reason: Optional[str] = None
    is_deleted: bool = False
    deletion_reason: Optional[str] = None
    deletion_time: Optional[datetime] = None
