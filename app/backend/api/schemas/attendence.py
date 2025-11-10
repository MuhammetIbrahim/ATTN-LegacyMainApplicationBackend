from pydantic import BaseModel, Field, ConfigDict,field_validator
from uuid import UUID
from datetime import datetime
from typing import Optional
import re

class AttendanceCreateRequest(BaseModel):
    """Request model for creating a new attendance session."""
    lesson_name: str = Field(..., description="The name of the lesson, e.g., 'Calculus I'.")
    start_time: datetime = Field(..., description="The start time in YYYY-MM-DDTHH:MM:SS.sssZ format.")
    end_time: datetime = Field(..., description="The end time in YYYY-MM-DDTHH:MM:SS.sssZ format.")
    security_option: int = Field(..., ge=1, le=3, description="Security level: 1=Low, 2=Medium, 3=High.")

    @field_validator('start_time', 'end_time', mode='before')
    def enforce_strict_utc_format(cls, v):
        """
        Validates that the datetime string is strictly in the
        YYYY-MM-DDTHH:MM:SS.sssZ format.
        """
        if isinstance(v, str):
            # This regex ensures the exact format, including 3 millisecond digits.
            utc_format_regex = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
            if not re.match(utc_format_regex, v):
                raise ValueError("Invalid format. Must be YYYY-MM-DDTHH:MM:SS.sssZ")
            
            # The format is correct, so we can now safely parse it.
            # Replacing 'Z' with '+00:00' is the standard way to handle this.
            return v.replace('Z', '+00:00')
        
        # If it's already a datetime object, do nothing.
        return v

class AttendanceDeleteRequest(BaseModel):
    """Request model for deleting an attendance session."""
    reason: str = Field(..., min_length=10, description="The reason for deleting the attendance session.")

# --- REFACTORED RESPONSE MODEL ---
class AttendanceResponse(BaseModel):
    """Response model for an attendance session."""
    attendance_id: UUID
    teacher_school_number: str = Field(description="The school number of the teacher who created the session.")
    teacher_full_name: str = Field(description="The full name of the teacher for easier display.")
    lesson_name: str
    start_time: datetime
    end_time: datetime
    security_option: int
    ip_address: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)
