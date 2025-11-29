import random
import time
from uuid import uuid4
from django.contrib.auth import login
from knox.models import AuthToken
from rest_framework import permissions, status
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import OTP, User
from django.db.models import Q

from accounts.serializers import AdminDeleteUserSerializer, AdminToggleUserSerializer, AdminVerifyUserSerializer, ChangePasswordSerializer, GenericMessageSerializer, LoginResponseSerializer, LoginSerializer, RegisterUserResponseSerializer, RegisterUserSerializer, ResetPasswordSerializer, SimpleStatusSerializer, UserSerializer, UserUpdateSerializer, VerifyOTPPostRequestSerializer

class LoginAPI(APIView):
    '''Login api endpoint'''
    permission_classes = (permissions.AllowAny,)
    serializer_class = LoginSerializer

    @extend_schema(request=LoginSerializer, responses={200: LoginResponseSerializer, 401: GenericMessageSerializer}, operation_id='login')
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as e:
            print(e)
            for field in list(e.detail):
                error_message = e.detail.get(field)[0]
                field = f"{field}: " if field != "non_field_errors" else ""
                response_data = {
                    "status": "error",
                    "error_message": f"{field} {error_message}",
                    "user": None,
                    "token": None,
                }
                return Response(response_data, status=status.HTTP_401_UNAUTHORIZED)
        else:
            user = serializer.validated_data
       
        login(request, user)

        # REMOVE THE FOLLOW COMMENTS IF YOU DON'T WANT 
        # MULTIPLE LOGINS FOR THE SAME USER
        # Delete existing token
        # AuthToken.objects.filter(user=user).delete()
        return Response({
            "user": UserSerializer(user).data,
            "token": AuthToken.objects.create(user)[1],
        })
    

class OTPLoginAPI(APIView):
    '''Login api endpoint using OTP'''
    permission_classes = (permissions.AllowAny,)
    serializer_class = VerifyOTPPostRequestSerializer

    @extend_schema(request=VerifyOTPPostRequestSerializer, responses={200: LoginResponseSerializer, 401: GenericMessageSerializer}, operation_id='otp_login')
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as e:
            print(e)
            for field in list(e.detail):
                error_message = e.detail.get(field)[0]
                field = f"{field}: " if field != "non_field_errors" else ""
                response_data = {
                    "status": "error",
                    "error_message": f"{field} {error_message}",
                    "user": None,
                    "token": None,
                }
                return Response(response_data, status=status.HTTP_401_UNAUTHORIZED)
        else:
            phone = serializer.validated_data.get('phone')
            otp_code = serializer.validated_data.get('otp')
            otp = OTP.objects.filter(phone=phone, otp=otp_code).first()
            if not otp:
                return Response({'error': 'Invalid OTP'}, status=status.HTTP_400_BAD_REQUEST)
            if otp.is_expired():
                return Response({'error': 'OTP has expired'}, status=status.HTTP_400_BAD_REQUEST)
            otp.delete()
            user = User.objects.filter(phone=phone).first()
            if not user:
                return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
            user.phone_verified = True
            user.save()
       
        login(request, user)

        # REMOVE THE FOLLOW COMMENTS IF YOU DON'T WANT 
        # MULTIPLE LOGINS FOR THE SAME USER
        # Delete existing token
        # AuthToken.objects.filter(user=user).delete()
        return Response({
            "user": UserSerializer(user).data,
            "token": AuthToken.objects.create(user)[1],
        })


class AdminLoginAPI(APIView):
    '''Admin/Staff-only login endpoint (same as LoginAPI but enforces staff/admin).'''
    permission_classes = (permissions.AllowAny,)
    serializer_class = LoginSerializer

    @extend_schema(request=LoginSerializer, responses={200: LoginResponseSerializer, 401: GenericMessageSerializer, 403: GenericMessageSerializer}, operation_id='admin_login')
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as e:
            print(e)
            for field in list(e.detail):
                error_message = e.detail.get(field)[0]
                field = f"{field}: " if field != "non_field_errors" else ""
                response_data = {
                    "status": "error",
                    "error_message": f"{field} {error_message}",
                    "user": None,
                    "token": None,
                }
                return Response(response_data, status=status.HTTP_401_UNAUTHORIZED)
        else:
            user = serializer.validated_data

        # Enforce admin/staff status
        if not (getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False)):
            return Response({
                "status": "error",
                "error_message": "Not authorized: admin/staff only",
                "user": None,
                "token": None,
            }, status=status.HTTP_403_FORBIDDEN)

        login(request, user)
        return Response({
            "user": UserSerializer(user).data,
            "token": AuthToken.objects.create(user)[1],
        })


class AdminListUsersAPIView(APIView):
    """List users (admin/staff only). Supports optional 'q' search across name, email, phone."""
    permission_classes = (permissions.IsAdminUser,)

    @extend_schema(
        parameters=[
            OpenApiParameter(name='q', type=OpenApiTypes.STR, location=OpenApiParameter.QUERY, required=False, description='Search by name, email or phone'),
        ],
        responses={200: UserSerializer(many=True)},
        operation_id='admin_list_users'
    )
    def get(self, request, *args, **kwargs):
        q = request.query_params.get('q')
        qs = User.objects.filter(deleted=False)
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))
        qs = qs.order_by('-created_at')
        return Response(UserSerializer(qs, many=True).data)



class RegisterUserAPI(APIView):
    '''Register User api endpoint'''
    permission_classes = (permissions.AllowAny,)
    serializer_class = RegisterUserSerializer

    @extend_schema(request=RegisterUserSerializer, responses={200: RegisterUserResponseSerializer, 401: GenericMessageSerializer}, operation_id='register')
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception as e:
            print(e)
            for field in list(e.detail):
                error_message = e.detail.get(field)[0]
                field = f"{field}: " if field != "non_field_errors" else ""
                response_data = {
                    "status": "error",
                    "error_message": f"{field} {error_message}",
                    "user": None,
                    "token": None,
                }
                return Response(response_data, status=status.HTTP_401_UNAUTHORIZED)
        else:
            user = serializer.save()
            user.is_active = True
            user.save()
            return Response({
                "user": UserSerializer(user).data,
                "token": AuthToken.objects.create(user)[1],
            })
        

class LogoutAPIView(APIView):
    '''Logout API endpoint'''
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = SimpleStatusSerializer

    @extend_schema(responses={200: SimpleStatusSerializer}, operation_id='logout')
    def post(self, request, *args, **kwargs):
        '''Logout user by invalidating their Knox token(s).'''
        # Try to delete just the token used for this request
        token = getattr(request, 'auth', None) or getattr(request, '_auth', None)
        if token is not None:
            try:
                token.delete()
            except Exception:
                pass
        else:
            # Fallback: delete all tokens for this user
            AuthToken.objects.filter(user=request.user).delete()

        return Response(
            {
                "status": "success",
                "message": "User logged out successfully",
            },
            status=status.HTTP_200_OK,
        )
    

class VerifyOTPAPI(APIView):
    '''Verify OTP api endpoint'''
    permission_classes = (permissions.AllowAny,)

    # Note: GET requests should not declare a request body. Use 'parameters' to document query params.
    @extend_schema(
        parameters=[
            OpenApiParameter(
                name='phone',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description='Phone number to which the OTP will be sent.'
            )
        ],
        responses={200: GenericMessageSerializer, 400: GenericMessageSerializer, 404: GenericMessageSerializer},
        operation_id='verify_otp_get'
    )
    def get(self, request, *args, **kwargs):
        '''Use this endpoint to send OTP to the user'''
        phone = request.query_params.get('phone')
        if not phone:
            return Response({'error': 'phone number is required'}, status=status.HTTP_400_BAD_REQUEST)
        code = random.randint(100000, 999999)
        try:
            otp = OTP.objects.filter(phone=phone).first()
            if otp:
                otp.delete()
            user = User.objects.filter(phone=phone).first()
            if not user:
                return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
            otp = OTP.objects.create(phone=phone, otp=code)
            otp.send_otp_to_user()
        except Exception as e:
            return Response({'error': 'Failed to send OTP'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({'message': 'OTP sent successfully'}, status=status.HTTP_200_OK)

    @extend_schema(request=VerifyOTPPostRequestSerializer, responses={200: GenericMessageSerializer, 400: GenericMessageSerializer, 404: GenericMessageSerializer}, operation_id='verify_otp_post')
    def post(self, request, *args, **kwargs):
        phone = request.data.get('phone')
        otp = request.data.get('otp')
        if not otp:
            return Response({'error': 'OTP is required'}, status=status.HTTP_400_BAD_REQUEST)
        otp = OTP.objects.filter(phone=phone, otp=otp).first()
        if not otp:
            return Response({'error': 'Invalid OTP'}, status=status.HTTP_400_BAD_REQUEST)
        if otp.is_expired():
            return Response({'error': 'OTP has expired'}, status=status.HTTP_400_BAD_REQUEST)
        otp.delete()
        user = User.objects.filter(phone=phone).first()
        if not user:
            return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
        user.phone_verified = True
        user.save()

        # login
        login(request, user)

        return Response({
            'message': 'OTP verified successfully',
            'token': AuthToken.objects.create(user)[1],
            'user': UserSerializer(user).data,
            }, status=status.HTTP_200_OK)
    

class ResetPasswordAPIView(APIView):
    '''API endpoint to reset user password'''

    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = ResetPasswordSerializer

    @extend_schema(request=ResetPasswordSerializer, responses={200: SimpleStatusSerializer, 400: GenericMessageSerializer}, operation_id='reset_password')
    def post(self, request, *args, **kwargs):
        '''Reset user password'''
        serializer = self.serializer_class(data=request.data)
        user = request.user
        if serializer.is_valid():
            if not user.phone_verified:
                return Response({'phone': 'Phone not verified.'}, status=status.HTTP_400_BAD_REQUEST)
            
            user.set_password(serializer.data.get('new_password'))
            user.save()
            return Response({'status': 'success'}, status=status.HTTP_200_OK)
        print(serializer.errors)
        # sanitize errors before sending
        for _, errors in serializer.errors.items():
            error = errors[0]
            break
        return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

class UserProfileAPIView(APIView):
    '''Get user profile'''
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = UserSerializer

    @extend_schema(responses={200: UserSerializer}, operation_id='user_profile_get')
    def get(self, request, *args, **kwargs):
        '''Get user profile for the logged in user'''
        user = request.user
        return Response(self.serializer_class(user).data)
    
    @extend_schema(request=UserUpdateSerializer, responses={200: UserSerializer, 400: GenericMessageSerializer}, operation_id='user_profile_put')
    def put(self, request, *args, **kwargs):
        '''Update user profile for the logged in user'''
        user = request.user
        serializer = UserSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(request=AdminToggleUserSerializer, responses={200: UserSerializer, 400: GenericMessageSerializer, 401: GenericMessageSerializer}, operation_id='user_profile_post')
    def post(self, request, *args, **kwargs):
        '''Use this to disable/enable a user account. To be used by admins only'''
        user = request.user
        if user.is_superuser:
            culprit_id = request.data.get('id')
            account_status = request.data.get('is_active')
            if user.id == culprit_id:
                return Response({'message': 'You cannot disable your own account'}, status=status.HTTP_400_BAD_REQUEST)
            if not culprit_id:
                return Response({'message': 'User ID is required'}, status=status.HTTP_400_BAD_REQUEST)
            if not (account_status == True or account_status == False):
                print(f"Account status: {account_status}")
                return Response({'message': 'Account status is required'}, status=status.HTTP_400_BAD_REQUEST)
            
            culprit = User.objects.filter(id=culprit_id, deleted=False).first()
            if not culprit:
                return Response({'message': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
            culprit.is_active = account_status == True
            culprit.save()
            return Response(UserSerializer(culprit).data)
        return Response({'message': 'You are not authorized to disable this account'}, status=status.HTTP_401_UNAUTHORIZED)
    
    @extend_schema(request=AdminDeleteUserSerializer, responses={200: GenericMessageSerializer, 400: GenericMessageSerializer, 401: GenericMessageSerializer}, operation_id='user_profile_delete')
    def delete(self, request, *args, **kwargs):
        '''Delete user account. To be used by admins only'''
        user = request.user
        if user.is_superuser:
            culprit_id = request.data.get('id')
            if user.id == culprit_id:
                return Response({'message': 'You cannot delete your own account'}, status=status.HTTP_400_BAD_REQUEST)
            if not culprit_id:
                return Response({'message': 'User ID is required'}, status=status.HTTP_400_BAD_REQUEST)
            culprit = User.objects.filter(id=culprit_id, deleted=False).first()
            if not culprit:
                return Response({'message': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
            culprit.deleted = True
            culprit.save()
            return Response({'message': 'User account deleted successfully'})
        return Response({'message': 'You are not authorized to delete this account'}, status=status.HTTP_401_UNAUTHORIZED)
    

class ChangePasswordAPIView(APIView):
    '''API endpoint to change user password'''

    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = ChangePasswordSerializer

    @extend_schema(request=ChangePasswordSerializer, responses={200: SimpleStatusSerializer, 400: GenericMessageSerializer}, operation_id='change_password')
    def post(self, request, *args, **kwargs):
        '''Change user password'''
        user = request.user
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            if not user.check_password(serializer.data.get('old_password')):
                return Response({'old_password': 'Wrong password.'}, status=status.HTTP_400_BAD_REQUEST)
            user.set_password(serializer.data.get('new_password'))
            user.save()
            return Response({'status': 'success', 'message': 'Password changed successfully'}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserPreferenceAPIView(APIView):
    '''API endpoint to get and update a user's preferences'''
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = UserSerializer

    @extend_schema(responses={200: UserSerializer}, operation_id='user_preferences_get')
    def get(self, request, *args, **kwargs):
        '''Get user preferences for the logged in user'''
        user = request.user
        return Response(self.serializer_class(user).data)

    @extend_schema(request=UserUpdateSerializer, responses={200: UserSerializer, 400: GenericMessageSerializer}, operation_id='user_preferences_put')
    def put(self, request, *args, **kwargs):
        '''Update user preferences for the logged in user'''
        user = request.user
        serializer = self.serializer_class(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



class AdminVerifyUserAPIView(APIView):
    """Mark a user's admin verification status. Staff-only endpoint."""
    permission_classes = (permissions.IsAdminUser,)
    serializer_class = AdminVerifyUserSerializer

    @extend_schema(
        request=AdminVerifyUserSerializer,
        responses={
            200: UserSerializer,
            400: GenericMessageSerializer,
            401: GenericMessageSerializer,
            403: GenericMessageSerializer,
            404: GenericMessageSerializer,
        },
        operation_id='admin_verify_user',
        description='Set admin verification status for a user by id. Staff-only.'
    )
    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            # return first error message consistently
            first_field, errors = next(iter(serializer.errors.items()))
            first_error = errors[0]
            return Response({'message': f'{first_field}: {first_error}'}, status=status.HTTP_400_BAD_REQUEST)

        user_id = serializer.validated_data['id']
        admin_verified = serializer.validated_data.get('admin_verified', True)

        target = User.objects.filter(id=user_id, deleted=False).first()
        if not target:
            return Response({'message': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

        target.admin_verified = bool(admin_verified)
        target.save(update_fields=['admin_verified', 'updated_at'])
        return Response(UserSerializer(target).data, status=status.HTTP_200_OK)