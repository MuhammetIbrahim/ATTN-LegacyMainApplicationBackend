from fastapi import (
    APIRouter, Depends, HTTPException, status,
    Request, File, UploadFile
)
from typing import List, Optional
from uuid import UUID

from ..services.student_service import StudentService, ServiceError
from ..models.db_models import User
# REFACTORED: Import the new response schemas
from .schemas.attendence import AttendanceResponse
from .schemas.attendence_record import AttendanceRecordResponse
from .schemas.user import UserResponse

from .auth import get_current_user
from .dependencies import get_student_service, get_client_ip
from .utilities.limiter import limiter

router = APIRouter(prefix="/student", tags=["Student Endpoints"])

def _verify_student_role(user: User):
    """Helper function to verify the current user is a student."""
    if "Student" not in user.role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation is only valid for students."
        )

# REFACTORED: Endpoint updated to use new service method and response model
@router.get(
    "/sessions/find",
    response_model=List[AttendanceResponse],
    summary="Find active attendance sessions by name"
)
@limiter.limit("20/minute")
async def find_active_sessions(
    request: Request,
    lesson_name: str,
    teacher_name: str,
    user: User = Depends(get_current_user),
    service: StudentService = Depends(get_student_service)
):
    """
    Checks if a lesson given by a specific teacher is currently active and open for attendance.
    Returns a list of all matching active sessions if there are name conflicts.
    """
    _verify_student_role(user)
    # REFACTORED: Call the new service method
    active_sessions = await service.find_active_sessions_by_name(lesson_name, teacher_name)
    # It's not an error if no sessions are found; returning an empty list is correct.
    return active_sessions

@router.post(
    "/attendances/{attendance_id}/attend",
    response_model=AttendanceRecordResponse,
    summary="Attempt to join a specific attendance session"
)
@limiter.limit("10/minute")
async def attend_to_attendance(
    request: Request,
    attendance_id: UUID,
    normal_image: Optional[UploadFile] = File(None),
    user: User = Depends(get_current_user),
    service: StudentService = Depends(get_student_service),
    client_ip: str = Depends(get_client_ip)
):
    """
    Allows a student to attempt to join an active session with a known `attendance_id`.
    This endpoint should be called after finding a session via '/sessions/find'.
    - For Security Option 3, the `normal_image` file must be uploaded as `multipart/form-data`.
    """
    _verify_student_role(user)

    normal_image_bytes = await normal_image.read() if normal_image else None
    
    try:
        created_record = await service.attend_to_attendance(
            student=user,
            attendance_id=attendance_id,
            student_ip=client_ip,
            normal_image_bytes=normal_image_bytes
        )
        
        # Enrich the response with the student's own user data
        return AttendanceRecordResponse(
            **created_record.model_dump(),
            student=UserResponse.model_validate(user)
        )
    except ServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred: {e}")

@router.get(
    "/attendances/{attendance_id}/status",
    response_model=AttendanceRecordResponse,
    summary="Check my attendance status in a specific session"
)
@limiter.limit("20/minute")
async def get_my_attendance_status(
    request: Request,
    attendance_id: UUID,
    user: User = Depends(get_current_user),
    service: StudentService = Depends(get_student_service)
):
    """
    Allows a student to query their own attendance status in a specific session.
    Used especially to check the result of asynchronous operations like face verification.
    """
    _verify_student_role(user)
    try:
        record = await service.get_my_attendance_status(attendance_id, user)
    except ServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Your attendance record for this session was not found, or the session does not exist."
        )

    return AttendanceRecordResponse(
        **record.model_dump(),
        student=UserResponse.model_validate(user)
    )
