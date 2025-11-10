from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import Optional
from .user import UserResponse

class AttendanceRecordDeleteRequest(BaseModel):
    """Request model for deleting an attendance record."""
    reason: str = Field(..., min_length=10, description="The reason for deleting the student's record.")

class AttendanceRecordResponse(BaseModel):
    """Response model for a student's attendance record, enriched with student info."""
    attendance_id: UUID
    is_attended: bool = Field(description="Whether the student was marked as present.")
    attendance_time: Optional[datetime] = Field(None, description="The exact time of attendance.")
    fail_reason: Optional[str] = Field(None, description="The reason for failure, if any.")
    
    # The student associated with this record.
    student: UserResponse = Field(description="The student user associated with this record.")
    
    model_config = ConfigDict(from_attributes=True)
