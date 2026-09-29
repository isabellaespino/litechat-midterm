from django import template

from chat.markdown import render_markdown

register = template.Library()


@register.filter
def markdown(text):
    """Render a model reply's Markdown as sanitized HTML (see chat/markdown.py)."""
    return render_markdown(text)
