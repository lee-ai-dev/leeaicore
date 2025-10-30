from enum import Enum


class UserType(Enum):
    ADMIN = "ADMIN"
    RESTAURANT = "RESTAURANT"
    USER = "USER"

class Status(Enum):
    APPROVED = "APPROVED"
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"