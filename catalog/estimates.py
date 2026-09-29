"""Rough "how far does my credit go" estimates for the landing page.

Uses the same cost function (and rounding up) as real charges. The token counts are
an assumption, stated on the page: a short message in a new chat. Real charges use
each reply's actual usage, and longer chats cost more because history is resent.
"""

from billing.services import reply_cost_micros

ASSUMED_INPUT_TOKENS = 500
ASSUMED_OUTPUT_TOKENS = 300


def estimate_messages(model, budget_micros, input_tokens=ASSUMED_INPUT_TOKENS,
                      output_tokens=ASSUMED_OUTPUT_TOKENS):
    """Return (cost per message in µ$, messages the budget buys). None when free."""
    per_message = reply_cost_micros(
        input_tokens,
        output_tokens,
        model.input_price_micros_per_mtok,
        model.output_price_micros_per_mtok,
    )
    return per_message, (budget_micros // per_message if per_message else None)
