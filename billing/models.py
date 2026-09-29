from django.conf import settings
from django.db import models


class Wallet(models.Model):
    """A user's prepaid balance. Only billing.services changes balance_micros."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, primary_key=True
    )
    # Signed: a reply is charged its actual cost, which can take the balance slightly negative.
    balance_micros = models.BigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Wallet of {self.user}"


class CreditTransaction(models.Model):
    """Append-only ledger. The sum of a user's amounts equals their wallet balance."""

    class Kind(models.TextChoices):
        SIGNUP = "signup", "Sign-up credit"
        TOPUP = "topup", "Top-up"
        CHARGE = "charge", "Charge"
        ADJUSTMENT = "adjustment", "Adjustment"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="credit_transactions",
    )
    amount_micros = models.BigIntegerField()
    kind = models.CharField(max_length=20, choices=Kind.choices)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "credit transaction"

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount_micros} µ$ for {self.user}"
