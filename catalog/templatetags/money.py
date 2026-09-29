from django import template

from config.money import format_dollars, format_dollars_precise

register = template.Library()


@register.filter
def dollars(micros):
    """Micro-dollars as dollars and cents, rounded down: 1_999_999 -> $1.99."""
    return format_dollars(micros)


@register.filter
def dollars_precise(micros):
    """Micro-dollars with up to 6 decimal places: 2_200 -> $0.0022."""
    return format_dollars_precise(micros)
