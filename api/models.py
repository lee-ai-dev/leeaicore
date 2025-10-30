from django.db import models
import string
import random
from accounts.models import Restaurant, User
from leeaicore.sysutils.constants import Status as SS
from leeaicore.sysutils.models import TimeStampedModel
from django.db import IntegrityError
from django.db.models.signals import m2m_changed
from django.dispatch import receiver
from leeaicore.sysutils.constants import OrderStatus, PaymentStatus, ComplaintStatus


# Order ID generator that does NOT touch the DB during import/app checks
def generate_order_id() -> str:
    """Generate order id (ORD-XXXXXXXX) without querying the DB.
    Uniqueness is enforced with retries in Order.save().
    """
    alphabet = string.ascii_uppercase + string.digits
    return 'ORD-' + ''.join(random.choices(alphabet, k=8))

class Dish(TimeStampedModel):
    '''Dish/meal model'''
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE)
    name = models.CharField(max_length=200)
    description = models.CharField(max_length=500)
    currency = models.CharField(max_length=5, default='GHC')
    in_stock = models.BooleanField(default=True)
    price = models.PositiveIntegerField(default=0)
    type = models.CharField(max_length=50)
    tag = models.CharField(max_length=20)
    availability = models.CharField(max_length=50, default='Always Available')

    def __str__(self):
        return f"{self.name}"
    

class Table(TimeStampedModel):
    '''Seat/table model for storing available seats or tables in the restaurants'''
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE, null=True, blank=True)
    table_id = models.CharField(max_length=10)
    capacity = models.PositiveSmallIntegerField(default=1)
    type = models.CharField(max_length=15)
    description = models.CharField(max_length=250, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    buffer_time = models.CharField(max_length=10, blank=True, null=True)
    currency = models.CharField(max_length=10)
    price = models.FloatField(default=0.0)
    available = models.BooleanField(default=True)

    def __str__(self):
        return f"Table {self.table_id}: {self.currency}{self.price}"



class OrderItem(TimeStampedModel):
    '''OrderItem model for storing individual dish and quantity'''
    dish = models.ForeignKey(Dish, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"{self.dish.name} x {self.quantity}"

class Order(TimeStampedModel):
    '''Order model for storing order information'''
    ord_id = models.CharField(max_length=15, unique=True, default=generate_order_id)
    user = models.ForeignKey('accounts.User', on_delete=models.PROTECT)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT)
    items = models.ManyToManyField(OrderItem)
    total_price = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=50, default='Pending')
    delivery_address = models.CharField(max_length=500)
    payment_method = models.CharField(max_length=50, default='Cash on Delivery')
    payment_status = models.CharField(max_length=50, default='Unpaid')
    currency = models.CharField(max_length=5, default='GHC')
    special_instructions = models.CharField(max_length=500, blank=True, null=True)

    def __str__(self):
        return f"Order {self.ord_id} by {self.user.name}"
    
    # collision-safe save for ord_id; total is managed via m2m signal
    def save(self, *args, **kwargs):
        retries = kwargs.pop("retries", 3)
        try:
            return super().save(*args, **kwargs)
        except IntegrityError as e:
            if "ord_id" in str(e).lower() and retries > 0:
                self.ord_id = generate_order_id()
                return self.save(*args, retries=retries - 1, **kwargs)
            raise
    
class Reservation(TimeStampedModel):
    '''model for storing table reservations'''
    table = models.ForeignKey(Table, on_delete=models.CASCADE)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=[(s.value, s.value) for s in SS], default=SS.PENDING.value)
    
    def __str__(self):
        return f"RSV (Table {self.table.table_id}): {self.status}"


# Keep order total in sync with items through m2m changes
@receiver(m2m_changed, sender=Order.items.through)
def update_order_total(sender, instance: Order, action, **kwargs):
    if action in ("post_add", "post_remove", "post_clear"):
        total = sum(item.dish.price * item.quantity for item in instance.items.all())
        Order.objects.filter(pk=instance.pk).update(total_price=total)


class Payment(TimeStampedModel):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=5, default='GHC')
    provider = models.CharField(max_length=50, default='MOCK')
    status = models.CharField(max_length=20, default=PaymentStatus.PENDING.value)
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    client_secret = models.CharField(max_length=200, blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.provider} {self.status} {self.amount}{self.currency} for {self.order.ord_id}"


class Complaint(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    restaurant = models.ForeignKey(Restaurant, on_delete=models.SET_NULL, blank=True, null=True)
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, blank=True, null=True)
    subject = models.CharField(max_length=120)
    message = models.TextField()
    status = models.CharField(max_length=20, default=ComplaintStatus.OPEN.value)

    def __str__(self):
        return f"Complaint #{self.id} {self.status}"
