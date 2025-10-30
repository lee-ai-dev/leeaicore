from rest_framework.permissions import BasePermission

from leeaicore.sysutils.constants import UserType



class IsSuperuser(BasePermission):
    """
    Allows access only to superusers.
    """
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_superuser
    
class IsStaffAdmin(BasePermission):
    """
    Allows access only to staff/admin members.
    """
    def has_permission(self, request, view):
        user = request.user
        return user.is_authenticated and (user.is_staff or user.user_type == UserType.ADMIN.value)
    
class IsRestaurantUser(BasePermission):
    """
    Allows access only to restaurant users.
    """
    def has_permission(self, request, view):
        user = request.user
        return user.is_authenticated and user.user_type == UserType.RESTAURANT.value