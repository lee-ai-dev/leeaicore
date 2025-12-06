from django.contrib.auth import authenticate
from rest_framework import serializers

from accounts.models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        exclude = ["password", "groups", "user_permissions"]


class CreateUserSerializer(serializers.ModelSerializer):
    """Serializer for creating a user from admin panel"""

    class Meta:
        model = User
        fields = ["email", "phone", "name", "address", "avatar", "password"]
        extra_kwargs = {
            "password": {"write_only": True},
            "email": {"required": True},
            "phone": {"required": True},
        }

    def create(self, validated_data):
        return User.objects.create_user(
            phone=validated_data.get("phone"),
            email=validated_data.get("email"),
            password=validated_data.get("password"),
            name=validated_data.get("name"),
            address=validated_data.get("address"),
            avatar=validated_data.get("avatar"),
        )


class LoginSerializer(serializers.Serializer):
    email = serializers.CharField()
    password = serializers.CharField()

    def validate(self, data):
        user = authenticate(**data)
        if user and user.is_active and ((hasattr(user, "deleted") and user.deleted == False) or not hasattr(user, "deleted")):
            return user
        raise serializers.ValidationError("Incorrect Credentials")


class RegisterUserSerializer(serializers.ModelSerializer):
    referral_code = serializers.CharField(required=False, allow_blank=True)
    class Meta:
        model = User
        fields = ("email", "phone", "password", "name", "address", "referral_code")
        extra_kwargs = {"password": {"write_only": True}, "email": {"required": True}, "phone": {"required": True}}

    def validate(self, attrs):
        if User.objects.filter(email=attrs.get("email")).exists():
            raise serializers.ValidationError("Email already exists")
        if User.objects.filter(phone=attrs.get("phone")).exists():
            raise serializers.ValidationError("Phone already exists")
        return attrs

    def create(self, validated_data):
        user = User.objects.create_user(
            phone=validated_data.get("phone"),
            email=validated_data.get("email"),
            password=validated_data.get("password"),
            name=validated_data.get("name"),
            address=validated_data.get("address")
        )
        return user


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField()
    new_password = serializers.CharField()
    confirm_password = serializers.CharField()

    def validate(self, data):
        if data.get("new_password") != data.get("confirm_password"):
            raise serializers.ValidationError("Passwords do not match")
        return data


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.CharField()
    new_password = serializers.CharField()
    confirm_password = serializers.CharField()

    def validate(self, data):
        if not User.objects.filter(email=data.get("email")).exists():
            raise serializers.ValidationError("Email does not exist")
        return data



# ----- APIView documentation serializers -----

class PingResponseSerializer(serializers.Serializer):
    message = serializers.CharField()


class LoginResponseSerializer(serializers.Serializer):
    user = UserSerializer()
    token = serializers.CharField()


class RegisterUserResponseSerializer(serializers.Serializer):
    user = UserSerializer()
    token = serializers.CharField()


class GenericMessageSerializer(serializers.Serializer):
    message = serializers.CharField()


class SimpleStatusSerializer(serializers.Serializer):
    status = serializers.CharField()
    message = serializers.CharField(required=False, allow_blank=True)

class VerifyOTPGetRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=10)


class VerifyOTPPostRequestSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=10)
    otp = serializers.CharField()


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
			'email', 'phone', 'name', 'address', 'avatar',
			'preferred_notification_email', 'preferred_notification_phone',
			'profile_registration_status',
        )
        extra_kwargs = {field: {"required": False} for field in fields}


class AdminToggleUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    is_active = serializers.BooleanField()


class AdminDeleteUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()


class ChatroomIdResponseSerializer(serializers.Serializer):
    chatroom_id = serializers.CharField()


class RedeemReferralResponseSerializer(serializers.Serializer):
    redeemed_points = serializers.IntegerField()
    cash_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    remaining_points = serializers.IntegerField()
    wallet_balance = serializers.DecimalField(max_digits=10, decimal_places=2)

# --- Admin actions ---
class AdminVerifyUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    admin_verified = serializers.BooleanField(required=False, default=True)
