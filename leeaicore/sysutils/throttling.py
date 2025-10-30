from rest_framework.throttling import ScopedRateThrottle
from django.conf import settings
from leeaicore.sysutils.constants import UserRole


class RoleBasedScopedRateThrottle(ScopedRateThrottle):
    """
    Extends ScopedRateThrottle to support role-based rates using keys like
    "<role>:<scope>" in DEFAULT_THROTTLE_RATES. Falls back to the plain scope
    rate if a role-specific rate isn't configured.
    Roles: anonymous | user | restaurant | admin
    """

    def get_rate(self):
        # Determine role bucket
        request = getattr(self, 'request', None)
        role_key = 'anonymous'
        if request and request.user and request.user.is_authenticated:
            # Admin bucket first
            if getattr(request.user, 'is_staff', False) or getattr(request.user, 'is_superuser', False):
                role_key = 'admin'
            else:
                role_val = getattr(request.user, 'role', None)
                if role_val == UserRole.RESTAURANT.value:
                    role_key = 'restaurant'
                else:
                    role_key = 'user'

        # Try role-specific rate first
        if self.scope:
            role_scope = f"{role_key}:{self.scope}"
            if role_scope in self.THROTTLE_RATES:
                return self.THROTTLE_RATES[role_scope]

        # Fallback to plain scope
        return super().get_rate()

    def allow_request(self, request, view):
        # Bypass throttling in DEBUG/test environments to keep tests stable
        if getattr(settings, 'DEBUG', False):
            return True
        # Store request for role detection in get_rate
        self.request = request
        return super().allow_request(request, view)
