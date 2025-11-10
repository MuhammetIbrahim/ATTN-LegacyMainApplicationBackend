# app/backend/models/db_models.py

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
from uuid import UUID

class User(BaseModel):
    """
    Represents a user in the system, mapping to the 'Users' table.
    """
    user_school_number: str = Field(..., description="Unique identifier for each user, acting as the Primary Key")
    user_full_name: str
    role: str =Field(...,description="Can be Teacher,Student,Admin,Demo_Teacher,Demo_Student")

class Attendance(BaseModel):
    """
    Represents an attendance session, mapping to the 'Attendances' table.
    """
    attendance_id: UUID = Field(..., description="Unique identifier for the attendance session")
    teacher_school_number: str = Field(..., description="FK linking to the teacher who started the session")
    lesson_name: str
    ip_address: Optional[str] = None
    start_time: datetime
    end_time: datetime
    security_option: int
    is_deleted: bool = False
    deletion_reason: Optional[str] = None
    deletion_time: Optional[datetime] = None

class AttendanceRecord(BaseModel):
    """
    Represents a single student's record for an attendance session,
    mapping to the 'AttendanceRecords' table.
    """
    attendance_id: UUID = Field(..., description="FK linking to the specific attendance session")
    student_number: str = Field(..., description="FK linking to the student")
    is_attended: bool = False
    attendance_time: Optional[datetime] = None
    fail_reason: Optional[str] = None
    is_deleted: bool = False
    deletion_reason: Optional[str] = None
    deletion_time: Optional[datetime] = None