from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import viewsets as vs
from accounts.views import *


urlpatterns = [
    # path('', PingAPI.as_view(), name='ping'),
]

# accounts | authentications
urlpatterns += [
    path('login/', LoginAPI.as_view(), name='login'),
    path('adminlogin/', AdminLoginAPI.as_view(), name='admin_login'),
    path('otplogin/', OTPLoginAPI.as_view(), name='otp_login'),
    path('logout/', LogoutAPIView.as_view(), name='logout'),
    path('verifyotp/', VerifyOTPAPI.as_view(), name='verifyotp'),
    path('register/', RegisterUserAPI.as_view(), name='register'),
    path('userprofile/', UserProfileAPIView.as_view(), name='userprofile'),
    path('changepassword/', ChangePasswordAPIView.as_view(), name='changepassword'),
    path('resetpassword/', ResetPasswordAPIView.as_view(), name='resetpassword'),
    path('userpreferences/', UserPreferenceAPIView.as_view(), name='userpreferences'),
    path('admin/verifyuser/', AdminVerifyUserAPIView.as_view(), name='admin_verify_user'),
    path('admin/users/', AdminListUsersAPIView.as_view(), name='admin_users'),
]