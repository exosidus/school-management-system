import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-secret-key-change-in-production"
    DATABASE_URL = os.environ.get("DATABASE_URL") or "elemis.db"

    # School Configuration
    SCHOOL_NAME = "Secondary School"
    SCHOOL_CODE = "ESS001"
    ACADEMIC_YEAR = "2025/2026"

    # Grade Configuration
    GRADES = [9, 10, 11, 12]
    SECTIONS = ["A", "B", "C", "D"]

    # Assessment Types
    ASSESSMENT_TYPES = ["quiz", "test", "assignment", "midterm", "final"]

    # Attendance Status
    ATTENDANCE_STATUS = ["present", "late", "absent"]

    # User Roles
    USER_ROLES = ["admin", "director", "teacher", "student", "parent"]

    # Grade Scale
    GRADE_SCALE = {"A": 90, "B": 80, "C": 70, "D": 60, "F": 0}

    # Ethiopian Subjects by Grade
    ETHIOPIAN_SUBJECTS = {
        9: [
            "አማርኛ",
            "English",
            "Mathematics",
            "Physics",
            "Chemistry",
            "Biology",
            "History",
            "Geography",
            "Civics",
        ],
        10: [
            "Ethiopian Languages",
            "English",
            "Mathematics",
            "Physics",
            "Chemistry",
            "Biology",
            "History",
            "Geography",
            "Civics",
        ],
        11: [
            "Ethiopian Languages",
            "English",
            "Mathematics",
            "Physics",
            "Chemistry",
            "Biology",
        ],
        12: [
            "Ethiopian Languages",
            "English",
            "Mathematics",
            "Physics",
            "Chemistry",
            "Biology",
        ],
    }
