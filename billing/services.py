from django.db import transaction
from django.db.models import F

from .models import CreditTransaction, Wallet


def get_wallet(user):
    wallet, _ = Wallet.objects.get_or_create(user=user)
    return wallet


def record_transaction(txn):
    """Save a new ledger entry and apply it to the wallet atomically.

    This is the only code path that changes a balance. The update uses F() so
    concurrent transactions never overwrite each other.
    """
    with transaction.atomic():
        Wallet.objects.get_or_create(user=txn.user)
        txn.save()
        Wallet.objects.filter(user=txn.user).update(
            balance_micros=F("balance_micros") + txn.amount_micros
        )
    return txn


def post_transaction(user, amount_micros, kind, note="", created_by=None):
    return record_transaction(
        CreditTransaction(
            user=user,
            amount_micros=amount_micros,
            kind=kind,
            note=note,
            created_by=created_by,
        )
    )
