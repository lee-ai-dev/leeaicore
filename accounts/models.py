'''
This module contains the models for the accounts application.
It includes the User, and OTP models.
These models are used to store information about the users 
and their otp information.

'''

from datetime import timedelta
from decimal import Decimal
import random
import string
from django.utils import timezone
from django.db import IntegrityError, transaction

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
# from django.contrib.auth import get_user_model
from leeaicore.sysutils.constants import UserRole
from leeaicore.sysutils.models import TimeStampedModel
from leeaicore.sysutils.constants import UserRole
from leeaicore.sysutils.services import send_sms

from .manager import AccountManager

# Restaurant ID generator that does NOT touch the DB during import/app checks
def generate_restaurant_id() -> str:
    """Generate restaurant id (LRID-XXXXXXXX) without querying the DB.
    Uniqueness is enforced with retries in Restaurant.save().
    """
    alphabet = string.ascii_uppercase + string.digits
    return 'LRID-' + ''.join(random.choices(alphabet, k=8))



class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    '''Custom User model for the application'''
    email = models.EmailField(max_length=50, unique=True)
    phone = models.CharField(max_length=15, unique=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=500, blank=True, null=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    role = models.CharField(max_length=20, default=UserRole.USER.value)
    admin_verified = models.BooleanField(default=False)
    role = models.CharField(max_length=20, default=UserRole.USER.value)  # USER, RESTAURANT, ADMIN
    deleted = models.BooleanField(default=False)  # Soft delete

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)

    phone_verified = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)

    # preferences
    preferred_notification_email = models.EmailField(max_length=50, blank=True, null=True)
    preferred_notification_phone = models.CharField(max_length=15, blank=True, null=True)

    objects = AccountManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['phone', 'name']


    def __str__(self):
        return self.name


class FCMDevice(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    token = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return f"{self.user.name} - {self.token[:10]}"

class Restaurant(TimeStampedModel):
    '''Restaurant model for storing restaurant information'''
    rid = models.CharField(unique=True, max_length=15, default=generate_restaurant_id)
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    phone = models.CharField(max_length=15)
    whatsapp = models.CharField(max_length=15, blank=True, null=True)
    instagram = models.CharField(max_length=255, blank=True, null=True)
    facebook = models.CharField(max_length=255, blank=True, null=True)
    twitter = models.CharField(max_length=255, blank=True, null=True)
    bank_account_number = models.CharField(max_length=50, blank=True, null=True)
    bank_name = models.CharField(max_length=255, blank=True, null=True)
    bank_code = models.CharField(max_length=50, blank=True, null=True)
    bank_branch = models.CharField(max_length=255, blank=True, null=True)
    website = models.URLField(blank=True, max_length=100)

    def __str__(self):
        return self.name
    
    # enforce uniqueness of rid on save
    def save(self, *args, **kwargs):
        retries = kwargs.pop("retries", 3)
        try:
            return super().save(*args, **kwargs)
        except IntegrityError as e:
            if "rid" in str(e).lower() and retries > 0:
                self.rid = generate_restaurant_id()
                return self.save(*args, retries=retries - 1, **kwargs)
            raise
    
class OperationalHours(TimeStampedModel):
    '''Operational Hours model for storing restaurant operational hours'''
    DAYS_OF_WEEK = [
        ("Monday", "Monday"),
        ("Tuesday", "Tuesday"),
        ("Wednesday", "Wednesday"),
        ("Thursday", "Thursday"),
        ("Friday", "Friday"),
        ("Saturday", "Saturday"),
        ("Sunday", "Sunday"),
    ]

    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE)
    day_of_week = models.CharField(max_length=10, choices=DAYS_OF_WEEK)
    open_time = models.TimeField()
    close_time = models.TimeField()

    class Meta:
        unique_together = ("restaurant", "day_of_week")

    def __str__(self):
        return f"{self.restaurant.name} - {self.day_of_week}: {self.open_time} to {self.close_time}"

class Wallet(TimeStampedModel):
    '''Wallet model for storing user wallet information'''
    restaurant = models.OneToOneField(Restaurant, on_delete=models.CASCADE)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    def deposit(self, amount) -> None:
        '''Deposit money into the wallet'''
        self.balance = (self.balance or Decimal('0.00')) + Decimal(str(amount))
        self.save()

    def withdraw(self, amount) -> None:
        '''Withdraw money from the wallet'''
        self.balance = (self.balance or Decimal('0.00')) - Decimal(str(amount))
        self.save()

    def __str__(self):
        return f"{self.user.name}'s Wallet"


class OTP(TimeStampedModel):
    '''One Time Password model'''
    phone = models.CharField(max_length=10)
    otp = models.CharField(max_length=6)

    def is_expired(self) -> bool:
        '''Returns True if the OTP is expired'''
        return (self.created_at + timedelta(minutes=30)) < timezone.now()
    
    def send_otp_to_user(self) -> None:
        '''Send the OTP to the user'''
        msg = f'Welcome to Oysloe Marketplace.\n\nYour OTP is {self.otp}\n\nRegards,\nOysloe Team'
        send_sms(message=msg, recipients=[self.phone])

    def __str__(self):
        return self.phone + ' - ' + self.otp