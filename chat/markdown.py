"""Safe Markdown rendering for model replies.

Two independent layers (loop 5 study §2.3):
1. markdown-it-py with raw HTML disabled, tables and strikethrough on, images off.
   It escapes any HTML the model writes and rejects javascript:/data: links.
2. nh3 (the Rust "ammonia" sanitizer) applied to the parser's output with a strict
   allowlist, so whatever the parser emits, only these tags, attributes and URL
   schemes can reach the page.

Model output can be steered by prompt injection, so images (which load a URL with no
click) and style attributes (which can load URLs via CSS) are never allowed.
"""

import re

import nh3
from django.utils.safestring import mark_safe
from markdown_it import MarkdownIt

_parser = (
    MarkdownIt("commonmark", {"html": False})
    .enable(["table", "strikethrough"])
    .disable("image")
)

ALLOWED_TAGS = {
    "p", "br", "strong", "em", "s", "del", "code", "pre", "blockquote", "ul", "ol", "li",
    "h1", "h2", "h3", "h4", "h5", "h6", "hr", "a", "table", "thead", "tbody", "tr", "th", "td",
}
ALLOWED_ATTRIBUTES = {"a": {"href", "title"}, "code": {"class"}}
URL_SCHEMES = {"http", "https", "mailto"}
LINK_REL = "noopener noreferrer nofollow"
_LANGUAGE_CLASS = re.compile(r"^language-[A-Za-z0-9_+-]+$")


def _attribute_filter(element, attribute, value):
    # Fenced code gets class="language-…"; keep that form only.
    if element == "code" and attribute == "class":
        return value if _LANGUAGE_CLASS.match(value) else None
    return value


def render_markdown(text):
    """Model Markdown -> sanitized HTML. The only place model output is marked safe."""
    html = _parser.render(text or "")
    return mark_safe(
        nh3.clean(
            html,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRIBUTES,
            attribute_filter=_attribute_filter,
            url_schemes=URL_SCHEMES,
            link_rel=LINK_REL,
        )
    )
