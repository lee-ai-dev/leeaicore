from enum import Enum


class UserRole(Enum):
    ADMIN = "ADMIN"
    RESTAURANT = "RESTAURANT"
    USER = "USER"

class Status(Enum):
    APPROVED = "APPROVED"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"


# More specific statuses for domain entities
class OrderStatus(Enum):
    PENDING = "PENDING"
    ON_GOING = "ON GOING"
    READY = "READY"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class PaymentStatus(Enum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class ComplaintStatus(Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"



