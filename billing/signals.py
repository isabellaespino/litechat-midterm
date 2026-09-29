from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import CreditTransaction
from .services import post_transaction


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def grant_signup_credit(sender, instance, created, raw=False, **kwargs):
    """Every new user, however created, gets a wallet and the sign-up credit."""
    if created and not raw:
        post_transaction(
            instance,
            settings.SIGNUP_CREDIT_MICROS,
            CreditTransaction.Kind.SIGNUP,
            note="Sign-up credit",
        )
