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
    path('restaurants/create/', vs.RestaurantCreateAPI.as_view(), name='restaurant_create'),
    path('restaurants/update/', vs.RestaurantUpdateAPI.as_view(), name='restaurant_update'),
    path('restaurants/profile/', vs.RestaurantProfileAPI.as_view(), name='restaurant_profile'),
    path('menu/', vs.MenuListAPI.as_view(), name='menu'),
    path('orders/place/', vs.PlaceOrderAPI.as_view(), name='place_order'),
    path('orders/<str:ord_id>/status/', vs.OrderStatusAPI.as_view(), name='order_status'),
    path('reservations/', vs.ReservationAPI.as_view(), name='reservations'),
    path('restaurants/orders/', vs.RestaurantOrdersAPI.as_view(), name='restaurant_orders'),
    path('restaurants/orders/<str:ord_id>/', vs.RestaurantOrderUpdateAPI.as_view(), name='restaurant_order_update'),
    path('restaurants/reservations/', vs.RestaurantReservationsAPI.as_view(), name='restaurant_reservations'),
    path('restaurants/reservations/<int:pk>/', vs.RestaurantReservationUpdateAPI.as_view(), name='restaurant_reservation_update'),
    path('restaurants/dishes/', vs.RestaurantDishListCreateAPI.as_view(), name='restaurant_dishes'),
    path('restaurants/dishes/<int:pk>/', vs.RestaurantDishDetailAPI.as_view(), name='restaurant_dishes_detail'),
    path('restaurants/tables/', vs.RestaurantTableListCreateAPI.as_view(), name='restaurant_tables'),
    path('restaurants/tables/<int:pk>/', vs.RestaurantTableDetailAPI.as_view(), name='restaurant_tables_detail'),
    path('restaurants/operational-hours/', vs.RestaurantOperationalHoursListCreateAPI.as_view(), name='restaurant_operational_hours'),
    path('restaurants/operational-hours/<int:pk>/', vs.RestaurantOperationalHoursDetailAPI.as_view(), name='restaurant_operational_hours_detail'),
    path('restaurants/operational-hours/batch/', vs.RestaurantOperationalHoursBatchAPI.as_view(), name='restaurant_operational_hours_batch'),
    path('complaints/', vs.ComplaintAPI.as_view(), name='complaints'),
    path('payments/intent/', vs.PaymentIntentAPI.as_view(), name='payment_intent'),
    path('payments/<str:ord_id>/confirm/', vs.PaymentConfirmAPI.as_view(), name='payment_confirm'),
    path('chatbot/intent/', vs.ChatbotIntentAPI.as_view(), name='chatbot_intent'),
    # admin base endpoints
    path('admin/restaurants/', vs.AdminRestaurantsAPI.as_view(), name='admin_restaurants'),
    path('admin/restaurants/<int:pk>/', vs.AdminRestaurantDetailAPI.as_view(), name='admin_restaurant_detail'),
    path('admin/restaurants/<int:pk>/users/', vs.AdminRestaurantUsersAPI.as_view(), name='admin_restaurant_users'),
    path('admin/restaurants/<int:pk>/payments/', vs.AdminRestaurantPaymentsAPI.as_view(), name='admin_restaurant_payments'),
    path('admin/restaurants/<int:pk>/suspend/', vs.AdminRestaurantSuspendAPI.as_view(), name='admin_restaurant_suspend'),
    path('admin/restaurants/<int:pk>/unsuspend/', vs.AdminRestaurantUnsuspendAPI.as_view(), name='admin_restaurant_unsuspend'),
    path('admin/orders/', vs.AdminOrdersAPI.as_view(), name='admin_orders'),
    path('admin/reservations/', vs.AdminReservationsAPI.as_view(), name='admin_reservations'),
    path('admin/tables/', vs.AdminTablesAPI.as_view(), name='admin_tables'),
    path('admin/dishes/', vs.AdminDishesAPI.as_view(), name='admin_dishes'),
    path('admin/payments/', vs.AdminPaymentsAPI.as_view(), name='admin_payments'),
]