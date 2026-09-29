from .services import get_wallet


def available_credit(request):
    if not request.user.is_authenticated:
        return {}
    return {"available_credit_micros": get_wallet(request.user).balance_micros}
