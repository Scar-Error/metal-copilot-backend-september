"""Single source of truth for email categorization.

Every individual ``EmailMessage`` gets exactly one tag from this module, and an
``EmailThread`` is tagged with the highest-priority tag among its messages.

Priority ladder, lowest to highest::

    other  <  rfq  <  quotation  <  po

``OTHER`` sits at the bottom on purpose: a thread where only some messages are
actionable still surfaces as actionable, while a thread where nothing is
actionable is still visibly tagged (as ``other``) rather than left blank.
"""

from __future__ import annotations

from typing import Iterable, Optional

RFQ = 'rfq'
QUOTATION = 'quotation'
PO = 'po'
OTHER = 'other'

EMAIL_CATEGORY_CHOICES = [
    (RFQ, 'RFQ'),
    (QUOTATION, 'Quotation'),
    (PO, 'PO'),
    (OTHER, 'Other'),
]

# Lower number = lower priority. A thread's tag is the message tag with the
# highest value. Ascending order also makes this safe to iterate directly.
CATEGORY_PRIORITY = {
    OTHER: 1,
    RFQ: 2,
    QUOTATION: 3,
    PO: 4,
}

VALID_CATEGORIES = frozenset(CATEGORY_PRIORITY)

DEFAULT_CATEGORY = OTHER


def normalize_category(value: Optional[str]) -> str:
    """Coerce any classifier output into a known category.

    The classifier is an LLM, so it can return junk, ``None``, or an empty
    string. Anything unrecognised degrades to ``other`` rather than poisoning
    the thread tag with a value the UI cannot render.
    """
    if not value:
        return DEFAULT_CATEGORY
    candidate = str(value).strip().lower()
    return candidate if candidate in VALID_CATEGORIES else DEFAULT_CATEGORY


def category_priority(value: Optional[str]) -> int:
    """Return the ladder position of ``value``.

    Unrecognised input normalises to ``other``, so garbage ranks at the bottom
    of the ladder rather than at some arbitrary level below it.
    """
    return CATEGORY_PRIORITY[normalize_category(value)]


def resolve_thread_category(categories: Iterable[Optional[str]]) -> str:
    """Pick the highest-priority tag from a thread's per-message tags.

    Every category has a distinct priority, so the result depends only on which
    tags are present, not on their order. An empty iterable yields ``other``.
    """
    best_category = DEFAULT_CATEGORY
    best_priority = 0

    for category in categories:
        priority = category_priority(category)
        if priority > best_priority:
            best_priority = priority
            best_category = normalize_category(category)

    return best_category
