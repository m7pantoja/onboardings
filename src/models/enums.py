from enum import StrEnum


class OnboardingStatus(StrEnum):
    PENDING = "pending"
    WAITING_TECHNICIAN = "waiting_technician"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class StepStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepName(StrEnum):
    CREATE_DRIVE_FOLDER = "create_drive_folder"
    CREATE_HOLDED_CONTACT = "create_holded_contact"
    NOTIFY_SLACK = "notify_slack"
    SEND_EMAIL = "send_email"
    NOTIFY_MANAGER = "notify_manager"
