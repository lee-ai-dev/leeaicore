from rest_framework.permissions import BasePermission

from leeaicore.sysutils.constants import UserRole



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
        # Allow if user is staff or has role ADMIN
        role = getattr(user, 'role', None)
        return user.is_authenticated and (user.is_staff or role == UserRole.ADMIN.value)
    
class IsRestaurantUser(BasePermission):
    """
    Allows access only to restaurant users.
    """
    def has_permission(self, request, view):
        user = request.user
        role = getattr(user, 'role', None)
        return user.is_authenticated and role == UserRole.RESTAURANT.value