# app/backend/modules/lesson_finder.py

from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

def _datetime_converter(date_str: str) -> datetime:
    """
    Parses the Microsoft JSON date format, converts it from UTC to a naive
    datetime object representing the time in UTC+3.
    """
    try:
        timestamp_ms = int(date_str.strip("/Date()/"))
        timestamp_s = timestamp_ms / 1000
        
        # 1. Create a timezone-aware datetime object in UTC.
        #    This is the modern, recommended way and avoids deprecation warnings.
        utc_datetime = datetime.fromtimestamp(timestamp_s, tz=timezone.utc)
        
        # 2. Define the target timezone (UTC+3).
        target_timezone = timezone(timedelta(hours=3))
        
        # 3. Convert the UTC datetime to the target timezone.
        target_datetime_aware = utc_datetime.astimezone(target_timezone)
        
        # 4. Return a naive datetime object by removing the timezone info,
        #    which matches the expectation of the original test.
        return target_datetime_aware.replace(tzinfo=None)
        
    except (ValueError, TypeError):
        # Handle cases where date_str is not in the expected format.
        return datetime.min

def find_lessons_for_day(schedule_data: List[Dict[str, Any]], target_date: datetime) -> List[Dict[str, Any]]:
    """
    Finds all lessons scheduled for a specific day from the raw schedule data.

    Args:
        schedule_data: The list of lesson dictionaries from the Aksis JSON response.
        target_date: The date for which to find lessons.

    Returns:
        A list of dictionaries, where each dictionary represents a lesson for the target day.
    """
    lessons_for_day = []
    
    for lesson in schedule_data:
        lesson_start_time = _datetime_converter(lesson.get("Start", ""))
        
        # Check if the lesson's start date matches the target date
        if lesson_start_time.date() == target_date.date():
            # Extract raw teacher name, split and get the last part
            raw_teacher = lesson.get("Hocalar", "")
            teacher_parts = raw_teacher.split(".")
            teacher_name = teacher_parts[-1].strip() if teacher_parts else ""
            
            lessons_for_day.append({
                "lesson_name": lesson.get("Title", "N/A"),
                "teacher_name": teacher_name,
                "start_time": lesson_start_time,
                "end_time": _datetime_converter(lesson.get("End", ""))
            })
            
    return lessons_for_day
