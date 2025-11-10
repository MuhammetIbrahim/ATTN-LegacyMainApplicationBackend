# tests/test_lesson_finder.py

import pytest
from datetime import datetime, timezone, timedelta
from app.backend.modules.lesson_finder import find_lessons_for_day, _datetime_converter

# --- Corrected Sample Data ---
# The timestamps have been updated to match the times in the comments.
SAMPLE_SCHEDULE_DATA = [
    {
        # Correct timestamp for 2025-02-18 11:40:00 UTC
        "Start": "/Date(1739878800000)/", 
        "End": "/Date(1739887200000)/", # 14:00 UTC
        "Title": "YBSB1008 - DATA STRUCTURES AND MANAGEMENT",
        "Hocalar": "Doç. Dr. ELİF KARTAL"
    },
    {
        # Correct timestamp for 2025-02-25 11:40:00 UTC
        "Start": "/Date(1740483600000)/", 
        "End": "/Date(1740492000000)/",
        "Title": "YBSB1008 - DATA STRUCTURES AND MANAGEMENT",
        "Hocalar": "Doç. Dr. ELİF KARTAL"
    },
    {
        # A second lesson on 2025-02-18 at 15:00:00 UTC
        "Start": "/Date(1739890800000)/", 
        "End": "/Date(1739899200000)/",
        "Title": "YBSF2004 - WEB DEVELOPMENT",
        "Hocalar": "Prof. Dr. AHMET YILMAZ"
    }
]

# --- Tests for the helper function ---

def test_datetime_converter():
    """
    Tests the private helper function that converts the Microsoft JSON date format.
    """
    # Corrected timestamp for 2025-02-18 11:40:00 UTC
    ms_date_string = "/Date(1739878800000)/"
    
    # The test now correctly expects 14:40 in UTC+3
    target_timezone = timezone(timedelta(hours=3))
    expected_datetime = datetime(2025, 2, 18, 14, 40)
    
    converted_time = _datetime_converter(ms_date_string)
    
    # We compare only the relevant parts, as the original test did.
    assert converted_time.year == expected_datetime.year
    assert converted_time.month == expected_datetime.month
    assert converted_time.day == expected_datetime.day
    assert converted_time.hour == expected_datetime.hour
    assert converted_time.minute == expected_datetime.minute


# --- Tests for the main function ---

def test_find_lessons_for_day_with_matching_lessons():
    """
    Test Case: Verifies that the function finds all lessons on a day
    that has scheduled lessons.
    """
    # We are looking for lessons on Feb 18, 2025. We expect to find 2.
    target_date = datetime(2025, 2, 18)
    
    found_lessons = find_lessons_for_day(SAMPLE_SCHEDULE_DATA, target_date)
    
    assert len(found_lessons) == 2
    # Check if the lesson names are correct
    lesson_names = {lesson['lesson_name'] for lesson in found_lessons}
    assert "YBSB1008 - DATA STRUCTURES AND MANAGEMENT" in lesson_names
    assert "YBSF2004 - WEB DEVELOPMENT" in lesson_names

def test_find_lessons_for_day_with_no_matching_lessons():
    """
    Test Case: Verifies that the function returns an empty list for a day
    with no scheduled lessons.
    """
    # We are looking for lessons on Feb 19, 2025. We expect to find 0.
    target_date = datetime(2025, 2, 19)
    
    found_lessons = find_lessons_for_day(SAMPLE_SCHEDULE_DATA, target_date)
    
    assert isinstance(found_lessons, list)
    assert len(found_lessons) == 0

def test_find_lessons_for_day_with_empty_data():
    """
    Test Case: Verifies that the function handles empty input gracefully.
    """
    target_date = datetime(2025, 2, 18)
    
    found_lessons = find_lessons_for_day([], target_date)
    
    assert isinstance(found_lessons, list)
    assert len(found_lessons) == 0

