import array
from pyfcm import FCMNotification
from .models import FCMDevice

push_service = FCMNotification(
    service_account_file="lee.json",
    project_id="leeaicore",
)

def send_push_notification(user, title, message):
    devices = FCMDevice.objects.filter(user=user)
    registration_ids = [device.token for device in devices]

    if not registration_ids:
        print("No devices found for user.")
        return "No devices"
    
    params_list = [
        {
            "fcm_token": token,
            "notification_title": title,
            "notification_body": message,
        }
        for token in registration_ids
    ]
    result = push_service.async_notify_multiple_devices(
        params_list=params_list,
    )

    print(f"Push notification sent to {len(registration_ids)} devices: {result}")

    return result


def send_mail(receipient: list, subject: str, message: str) -> None:
    """
    Send an email
    """
    from django.core.mail import send_mail
    from django.conf import settings

    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        receipient,
        fail_silently=False,
    )


import requests

from leeaicore import settings


def send_sms(message: str, recipients: array.array, sender: str = settings.SENDER_ID):
    '''Sends an SMS to the specified recipients'''
    header = {"api-key": settings.ARKESEL_API_KEY, 'Content-Type': 'application/json',
              'Accept': 'application/json'}
    SEND_SMS_URL = "https://sms.arkesel.com/api/v2/sms/send"
    payload = {
        "sender": sender,
        "message": message,
        "recipients": recipients
    } 
    try:
        response = requests.post(SEND_SMS_URL, headers=header, json=payload)
    except Exception as e:
        print(f"Error: {e}")
        return False
    else:
        print(response.json())
        return response.json()