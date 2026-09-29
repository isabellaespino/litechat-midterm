from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .services import get_wallet


@login_required
def credit(request):
    return render(
        request,
        "billing/credit.html",
        {
            "wallet": get_wallet(request.user),
            "transactions": request.user.credit_transactions.all(),
        },
    )
