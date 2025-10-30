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

# core restaurant features
urlpatterns += [
    path('menu/', vs.MenuListAPI.as_view(), name='menu'),
    path('orders/place/', vs.PlaceOrderAPI.as_view(), name='place_order'),
    path('orders/<str:ord_id>/status/', vs.OrderStatusAPI.as_view(), name='order_status'),
    path('reservations/', vs.ReservationAPI.as_view(), name='reservations'),
    path('complaints/', vs.ComplaintAPI.as_view(), name='complaints'),
    path('payments/intent/', vs.PaymentIntentAPI.as_view(), name='payment_intent'),
    path('payments/<str:ord_id>/confirm/', vs.PaymentConfirmAPI.as_view(), name='payment_confirm'),
    path('chatbot/intent/', vs.ChatbotIntentAPI.as_view(), name='chatbot_intent'),
]