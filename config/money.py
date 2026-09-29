"""Money helpers. All amounts are stored as whole micro-dollars (1 USD = 1_000_000)."""

from decimal import Decimal

MICROS_PER_DOLLAR = 1_000_000
MICROS_PER_CENT = 10_000


def dollars_to_micros(dollars):
    """Convert a Decimal dollar amount (at most 6 decimal places) to micro-dollars."""
    micros = Decimal(dollars) * MICROS_PER_DOLLAR
    if micros != micros.to_integral_value():
        raise ValueError(f"{dollars} has more than 6 decimal places")
    return int(micros)


def micros_to_dollars(micros):
    """Exact Decimal dollar value of a micro-dollar amount."""
    return Decimal(micros) / MICROS_PER_DOLLAR


def format_dollars(micros):
    """Dollars and cents, rounded down to the cent: 1_999_999 -> "$1.99", -1 -> "-$0.01"."""
    cents = micros // MICROS_PER_CENT  # floor division rounds toward negative infinity
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    return f"{sign}${whole:,}.{frac:02d}"


def format_dollars_precise(micros):
    """Up to 6 decimal places, at least 2: 300_000 -> "$0.30", 2_200 -> "$0.0022"."""
    sign = "-" if micros < 0 else ""
    whole, frac = divmod(abs(micros), MICROS_PER_DOLLAR)
    digits = f"{frac:06d}".rstrip("0").ljust(2, "0")
    return f"{sign}${whole:,}.{digits}"
