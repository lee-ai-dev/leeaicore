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
    CONFIRMED = "CONFIRMED"
    PREPARING = "PREPARING"
    READY = "READY"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


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



