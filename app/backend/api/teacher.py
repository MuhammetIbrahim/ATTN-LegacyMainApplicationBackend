from fastapi import APIRouter, Depends, HTTPException, status, Response, Request
from typing import List, Union, Optional
from uuid import UUID
from datetime import datetime, timezone
from pydantic import BaseModel, Field

# --- Gerekli tüm şemalar, servisler, modeller ve bağımlılıklar ---
from ..services.teacher_service import TeacherService, ServiceError, AuthorizationError
from ..models.db_models import User, Attendance
from ..models.redis_models import AttendanceRedis
from .schemas.attendence import (
    AttendanceCreateRequest,
    AttendanceResponse,
    AttendanceDeleteRequest
)
from .schemas.attendence_record import (
    AttendanceRecordResponse,
    AttendanceRecordDeleteRequest
)
from .schemas.user import UserResponse
from .auth import get_current_user
from .dependencies import get_teacher_service, get_client_ip
from .utilities.limiter import limiter

# --- Endpoint'e Özel İstek Modelleri ---
class FailStudentRequest(BaseModel):
    reason: str = Field(..., min_length=5, description="Öğrencinin neden başarısız sayıldığının açıklaması.")

# --- REFACTORED REQUEST MODEL ---
class AddStudentToHistoricalRequest(BaseModel):
    student_school_number: str = Field(..., description="Eklenecek öğrencinin okul numarası.")
    # ADDED: Include the student's full name for data integrity.
    student_full_name: str = Field(..., min_length=3, description="Eklenecek öğrencinin tam adı.")
    is_attended: bool = Field(description="Öğrencinin derse katılmış olarak mı ekleneceği.")
    reason: Optional[str] = Field(None, description="Eğer katılmadıysa, başarısızlık nedeni.")


router = APIRouter(prefix="/teacher", tags=["Teacher Endpoints"])

# --- YARDIMCI (HELPER) FONKSİYONLAR ---

def _verify_teacher_role(user: User):
    if "Teacher" not in user.role:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This operation is only valid for teachers.")

async def _get_and_verify_owner(attendance_id: UUID, user: User, service: TeacherService) -> Union[Attendance, AttendanceRedis]:
    try:
        return await service.get_and_verify_attendance_owner(attendance_id, user)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

# === BÖLÜM 1: YOKLAMA OTURUMU YÖNETİMİ ===

@router.post("/attendances", response_model=AttendanceResponse, status_code=status.HTTP_201_CREATED, summary="Start a new attendance session")
@limiter.limit("5/minute")
async def start_attendance(request: Request, create_request: AttendanceCreateRequest, user: User = Depends(get_current_user), service: TeacherService = Depends(get_teacher_service), client_ip: str = Depends(get_client_ip)):
    _verify_teacher_role(user)
    try:
        new_session = await service.start_attendance(teacher=user, lesson_name=create_request.lesson_name, ip_address=client_ip, start_time=create_request.start_time, end_time=create_request.end_time, security_option=create_request.security_option)
        return new_session
    except ServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/attendances/{attendance_id}/finish", status_code=status.HTTP_204_NO_CONTENT, summary="Finish an active attendance session")
@limiter.limit("5/minute")
async def finish_attendance(request: Request, attendance_id: UUID, user: User = Depends(get_current_user), service: TeacherService = Depends(get_teacher_service)):
    _verify_teacher_role(user)
    await _get_and_verify_owner(attendance_id, user, service)
    try:
        await service.finish_attendance(teacher=user, attendance_id=attendance_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except (ServiceError, AuthorizationError) as e:
         raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.get("/attendances/live", response_model=Optional[AttendanceResponse], summary="Get the single active attendance session for the teacher")
@limiter.limit("60/minute")
async def get_live_attendance(request: Request, user: User = Depends(get_current_user), service: TeacherService = Depends(get_teacher_service)):
    _verify_teacher_role(user)
    live_session = await service.get_live_attendance_by_teacher(teacher=user)
    return live_session

@router.get("/attendances/historical", response_model=List[AttendanceResponse], summary="List all past (historical) attendances for the teacher")
@limiter.limit("10/minute")
async def get_historical_attendances(request: Request, user: User = Depends(get_current_user), service: TeacherService = Depends(get_teacher_service)):
    _verify_teacher_role(user)
    attendances_from_db = await service.get_historical_attendances(teacher=user)
    response = []
    for att in attendances_from_db:
        att_dict = att.model_dump()
        att_dict['teacher_full_name'] = user.user_full_name
        response.append(AttendanceResponse(**att_dict))
    return response

@router.delete("/attendances/{attendance_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a historical attendance session")
@limiter.limit("5/minute")
async def delete_attendance(request: Request, attendance_id: UUID, delete_request: AttendanceDeleteRequest, user: User = Depends(get_current_user), service: TeacherService = Depends(get_teacher_service)):
    _verify_teacher_role(user)
    await _get_and_verify_owner(attendance_id, user, service)
    await service.delete_attendance(attendance_id=attendance_id, reason=delete_request.reason)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# === BÖLÜM 2: YOKLAMA KAYDI YÖNETİMİ ===

@router.get("/attendances/{attendance_id}/records", response_model=List[AttendanceRecordResponse], summary="Get all records for a specific attendance session")
@limiter.limit("60/minute")
async def get_attendance_records(request: Request, attendance_id: UUID, user: User = Depends(get_current_user), service: TeacherService = Depends(get_teacher_service)):
    _verify_teacher_role(user)
    attendance = await _get_and_verify_owner(attendance_id, user, service)
    is_live = isinstance(attendance, AttendanceRedis)
    enriched_records = await service.get_live_attendance_records(attendance_id) if is_live else await service.get_historical_attendance_records(attendance_id)
    return enriched_records

# --- Canlı Yoklama Kayıt İşlemleri ---

@router.post("/attendances/{attendance_id}/live/records/{student_school_number}/accept", response_model=AttendanceRecordResponse, summary="Manually accept a student's attendance in a live session")
@limiter.limit("200/minute")
async def accept_student_in_live_attendance(request: Request, attendance_id: UUID, student_school_number: str, user: User = Depends(get_current_user), service: TeacherService = Depends(get_teacher_service)):
    _verify_teacher_role(user)
    await _get_and_verify_owner(attendance_id, user, service)
    try:
        updated_record = await service.accept_student_attendance(attendance_id, student_school_number)
        if not updated_record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance record for the specified student not found.")
        return updated_record
    except ServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/attendances/{attendance_id}/live/records/{student_school_number}/fail", response_model=AttendanceRecordResponse, summary="Manually fail a student in a live session")
@limiter.limit("200/minute")
async def fail_student_in_live_attendance(request: Request, attendance_id: UUID, student_school_number: str, fail_request: FailStudentRequest, user: User = Depends(get_current_user), service: TeacherService = Depends(get_teacher_service)):
    _verify_teacher_role(user)
    await _get_and_verify_owner(attendance_id, user, service)
    try:
        updated_record = await service.fail_student_in_live_attendance(attendance_id, student_school_number, fail_request.reason)
        if not updated_record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance record for the specified student not found.")
        return updated_record
    except ServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

# --- Geçmiş Yoklama Kayıt İşlemleri ---

# --- REFACTORED ENDPOINT ---
@router.post("/attendances/{attendance_id}/historical/records", status_code=status.HTTP_201_CREATED, summary="Manually add a student to a historical attendance")
@limiter.limit("200/minute")
async def add_student_to_historical_attendance(request: Request, attendance_id: UUID, add_request: AddStudentToHistoricalRequest, user: User = Depends(get_current_user), service: TeacherService = Depends(get_teacher_service)):
    _verify_teacher_role(user)
    await _get_and_verify_owner(attendance_id, user, service)
    try:
        # Use the provided full name instead of a placeholder.
        student_to_add = User(
            user_school_number=add_request.student_school_number,
            user_full_name=add_request.student_full_name, # Use the name from the request
            role="Student"
        )
        await service.add_student_to_historical_attendance(attendance_id, student_to_add, add_request.is_attended, add_request.reason)
        return {"status": "success", "detail": f"Student {add_request.student_school_number} added to attendance {attendance_id}."}
    except ServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/attendances/{attendance_id}/historical/records/{student_school_number}/accept", summary="Manually accept a student in a historical attendance", status_code=status.HTTP_200_OK)
@limiter.limit("200/minute")
async def accept_student_in_historical_attendance(request: Request, attendance_id: UUID, student_school_number: str, user: User = Depends(get_current_user), service: TeacherService = Depends(get_teacher_service)):
    _verify_teacher_role(user)
    await _get_and_verify_owner(attendance_id, user, service)
    try:
        await service.accept_student_in_historical_attendance(attendance_id, student_school_number)
        return {"status": "success", "detail": f"Student {student_school_number} in attendance {attendance_id} marked as successful."}
    except ServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.post("/attendances/{attendance_id}/historical/records/{student_school_number}/fail", summary="Manually fail a student in a historical attendance", status_code=status.HTTP_200_OK)
@limiter.limit("200/minute")
async def fail_student_in_historical_attendance(request: Request, attendance_id: UUID, student_school_number: str, fail_request: FailStudentRequest, user: User = Depends(get_current_user), service: TeacherService = Depends(get_teacher_service)):
    _verify_teacher_role(user)
    await _get_and_verify_owner(attendance_id, user, service)
    try:
        await service.fail_student_in_historical_attendance(attendance_id, student_school_number, fail_request.reason)
        return {"status": "success", "detail": f"Student {student_school_number} in attendance {attendance_id} marked as failed."}
    except ServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

@router.delete("/attendances/{attendance_id}/records/{student_school_number}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a student's record from a historical attendance")
@limiter.limit("200/minute")
async def delete_student_from_attendance(request: Request, attendance_id: UUID, student_school_number: str, delete_request: AttendanceRecordDeleteRequest, user: User = Depends(get_current_user), service: TeacherService = Depends(get_teacher_service)):
    _verify_teacher_role(user)
    await _get_and_verify_owner(attendance_id, user, service)
    try:
        rows_deleted = await service.delete_student_from_attendance(attendance_id, student_school_number, delete_request.reason)
        if not rows_deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student record to be deleted was not found.")
    except ServiceError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    return Response(status_code=status.HTTP_204_NO_CONTENT)
