"""Work out the details of a contact from the email that introduced them.

Categorizing a thread is the only moment we see both halves of the information:
the From header tells us who wrote, the body tells us how to reach them. That
gives three things the Contacts page wants and nobody wants to type twice:

* a phone number, lifted from the signature (the tail of the message),
* a company name, read off the signature and failing that the email address,
* the guarantee that one person stays one contact, whatever case the address
  happens to be written in.

Two rules that shaped this module:

* Nothing here overwrites a value that is already stored. A phone number
  typed by hand always beats a number scraped off a signature, and the first
  signature seen for a thread wins over later ones, so the result does not
  depend on which message happened to be processed first.
* Internal senders are not contacts. Co.Ri.Metal is us, and @corimetal.it is
  excluded so that our own replies never end up in the contacts list.

Both fields are guesses about a stranger's letterhead, so they are left empty
rather than filled with something that only looks right: a phone number is only
taken from a line that actually says Tel/Mobile/Phone, and when neither is
found the Contacts page says so.
"""

import html
import re
from typing import Optional, Tuple

from contacts.models import Contact

# Our own mail domain: we are the sender, never a contact.
INTERNAL_EMAIL_DOMAINS = frozenset({'corimetal.it'})

# Domains where the part before the TLD is the company name.
_TLDS = frozenset({
    'it', 'com', 'org', 'net', 'co', 'io', 'eu', 'de', 'fr', 'es', 'nl',
    'be', 'at', 'ch', 'uk', 'us', 'ca', 'au', 'ru', 'cn', 'jp', 'in', 'br',
    'se', 'no', 'dk', 'fi', 'pl', 'cz', 'hu', 'ro', 'gr', 'pt', 'ie', 'nz',
    'za', 'mx', 'tr', 'ae', 'sa', 'il', 'info', 'biz', 'name', 'pro', 'app',
})

# Second level labels that belong to a country code (example.co.uk, not
# example.co + uk), so the company name is the label before them.
_SECOND_LEVEL_LABELS = frozenset({'co', 'com', 'org', 'net', 'gov', 'edu', 'ac'})

# A signature lives at the end of a message; scanning further back than this
# starts picking up phone numbers that belong to the body text instead.
_SIGNATURE_TAIL_CHARS = 2000

# How many lines at the end of the message can hold the company name: the person
# signs with their name, then the company, then the contact details.
_SIGNATURE_LINES = 6

# Phone labels, in priority order: Tel wins, Mobile second. The rest are the
# other spellings that turn up in signatures, tried in this order. There is
# deliberately no unlabelled fallback — the first free-standing number in a
# signature is far more often a zip code, a VAT number or a date than a phone.
_PHONE_LABELS = ('tel', 'mobile', 'telephone', 'phone', 'cell', 'cellulare')
_PHONE_LABELLED = {
    label: re.compile(
        rf'\b{label}\b\s*[\s.:\-–/]*'
        r'(?P<number>\+?\d[\d .()/+\-–]{4,}\d)',
        re.IGNORECASE,
    )
    for label in _PHONE_LABELS
}
_ONLY_DIGITS = re.compile(r'^[\d\s+()\-./]{6,}$')

# A number with fewer digits than this cannot be dialled from abroad: the zip
# code and the order number that show up in signatures are all this short.
_MIN_PHONE_DIGITS = 7

# Openings and closings sit right next to the company name in a signature and
# are not it.
_OPENING_OR_CLOSING = re.compile(
    r'^(?:dear|hi|hello|hey|best|kind|warm|sincerely|regards|thank|thanks'
    r'|cordiali|cordialmente|distinti saluti|saluti|grazie|ciao|a presto'
    r'|buongiorno|buonasera|gentile|salve|ps|p\.s)\b[\s,!.]*',
    re.IGNORECASE,
)

# Contact details and links are never the company name.
_NOT_A_COMPANY = re.compile(
    r'https?://|www\.|@|'
    r'\b(?:tel|phone|mobile|cell|fax|email|e-mail|skype|linkedin)\b\s*\.?\s*:',
    re.IGNORECASE,
)

# Street addresses: a signature prints the address under the company name, and
# "Via Roma 12, 20100 Milano" is not a company.
_ADDRESS = re.compile(
    r'\b(?:via|viale|piazza|corso|str|street|road|rd|avenue|ave|boulevard'
    r'|suite|floor|building|bldg|po\s+box|p\.?iva|cap|z\.?i\.?f|p\.?i\.?va'
    r'|tel|fax)\b'
    r'|\b\d{4,6}\b',
    re.IGNORECASE,
)

# The legal forms a company name can end in. A name ending in one of these is
# short enough to be read as a name even though it ends in a full stop, which is
# also how a sentence ends — the punctuation rule below depends on the
# difference.
_LEGAL_FORM = (
    r's\.?\s?r\.?\s?l\.?|s\.?\s?p\.?\s?a\.?|s\.?a\.?|s\.?p\.?a\.?|spa|srl'
    r'|sarl|inc|ltd|llc|limited|gmbh|ag|bv|b\.?v\.?|oy|ab|as|plc'
    r'|corp|corporation|co|company|group|holdings?'
)
_LEGAL_FORM_TAIL = re.compile(rf'(?:{_LEGAL_FORM})\.?$', re.IGNORECASE)
# A legal form on its own says which country, not which company.
_ONLY_LEGAL_FORM = re.compile(rf'^(?:{_LEGAL_FORM})\.?$', re.IGNORECASE)
# A line that ends the way prose ends, or the way a line of contact details
# ends, is not a company name.
_SENTENCE_END = re.compile(r'[.,:;!?]$')


def _looks_like_a_sentence(line: str) -> bool:
    """True when a line reads as prose or as a detail, not as a name."""
    if not _SENTENCE_END.search(line):
        return False
    # "Co.Ri.Metal S.R.L." and "Opti Manufacturing Inc." end in a full stop and
    # are names all the same.
    return not _LEGAL_FORM_TAIL.search(line)


def _name_words(value: str) -> set:
    """A name reduced to comparable words: 'Rossi, Luigi!' -> {'rossi', 'luigi'}."""
    return set(re.findall(r'[\w]+', (value or '').casefold()))




def _domain_of(email: str) -> str:
    """Lowercased domain part of an email address ('' when there is none)."""
    address = (email or '').strip().lower()
    if '@' not in address:
        return ''
    return address.rpartition('@')[2].split(':')[0]


def is_internal_email(email: str) -> bool:
    """True for our own mail domain, so we never become our own contact."""
    domain = _domain_of(email)
    if not domain:
        return False
    return any(
        domain == internal or domain.endswith(f'.{internal}')
        for internal in INTERNAL_EMAIL_DOMAINS
    )


def company_from_email(email: str) -> str:
    """Read a company name off an email address.

    Everything after the @ with the domain suffix removed, so that
    ``luigi@rossimax.it`` and ``luigi@mail.rossimax.it`` both give ``rossimax``.
    Returns '' when the address carries no usable domain.
    """
    domain = _domain_of(email)
    if not domain:
        return ''

    labels = [label for label in domain.split('.') if label]
    if labels and labels[0] == 'www':
        labels = labels[1:]
    if not labels:
        return ''

    if len(labels) > 1 and labels[-1] in _TLDS:
        if len(labels) > 2 and labels[-2] in _SECOND_LEVEL_LABELS:
            labels = labels[:-2]
        else:
            labels = labels[:-1]

    # Subdomains (mail.rossimax.it) collapse onto the base name.
    return labels[-1] if labels else ''


def format_company(name: str) -> str:
    """Present a derived company name the way a company would write it.

    An email domain is all lowercase, so ``dhl`` becomes ``DHL`` and
    ``rossimax`` becomes ``Rossimax``. A name that already contains a capital is
    left alone: it came from a signature, and that is the better source.
    """
    cleaned = ' '.join((name or '').split())
    if not cleaned or cleaned != cleaned.lower():
        return cleaned
    if len(cleaned) <= 4 and cleaned.isalpha():
        return cleaned.upper()
    return cleaned[0].upper() + cleaned[1:]


def _to_plain_text(body: str) -> str:
    """Flatten a (usually HTML) message body into text, one line per block."""
    text = re.sub(
        r'<(script|style)[^>]*>.*?</\1>',
        ' ',
        body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    text = re.sub(
        r'<\s*(br|/p|/div|/tr|/td|/li|/h[1-6])\b[^>]*>',
        '\n',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    return text.replace('\xa0', ' ')


def _clean_phone(raw: str) -> str:
    """Normalise a matched number to '+digits' (or bare digits)."""
    digits = re.sub(r'\D', '', raw)
    if len(digits) < _MIN_PHONE_DIGITS:
        return ''
    cleaned = f'+{digits}' if raw.lstrip().startswith('+') else digits
    return cleaned[:50]


def phone_from_signature(body: str) -> str:
    """Pull the sender's phone number out of a message signature.

    Only a line that actually says so is used, ``Tel`` before ``Mobile``; an
    unlabelled number is ignored on purpose, because in a signature the first
    free-standing number is far more often a zip code, a VAT number or a date
    than a telephone. Returns '' when there is no labelled number, and the
    contact is then shown as having no phone rather than a wrong one.
    """
    if not body:
        return ''

    # Only the tail: a number in the body of the email is usually something
    # else (a delivery address, a reference), while the signature is always last.
    signature = _to_plain_text(body)[-_SIGNATURE_TAIL_CHARS:]

    for label in _PHONE_LABELS:
        pattern = _PHONE_LABELLED[label]
        for match in pattern.finditer(signature):
            phone = _clean_phone(match.group('number'))
            if phone:
                return phone

    return ''


def company_from_signature(body: str, sender_name: str = '') -> str:
    """Read the sender's company name off their signature.

    A signature states the person, then the company, then the address and the
    phone numbers, so the company is the first line of the last few that is not
    the person we already know, an address, a link or a bare number. Returns ''
    when nothing in the signature is a company name, which is the common case
    for a newsletter and the reason the email address is the fallback.
    """
    if not body:
        return ''

    person = _name_words(sender_name)
    lines = [
        ' '.join(line.split())
        for line in _to_plain_text(body)[-_SIGNATURE_TAIL_CHARS:].splitlines()
    ]
    lines = [line for line in lines if line]

    for line in lines[-_SIGNATURE_LINES:]:
        if len(line) < 3:
            continue
        # The signature repeats the sender's own name, in a possibly different
        # order and punctuation than the From header gave it to us.
        if person and _name_words(line) == person:
            continue
        if _OPENING_OR_CLOSING.match(line):
            continue
        if _NOT_A_COMPANY.search(line) or _ADDRESS.search(line):
            continue
        if _ONLY_DIGITS.match(line) or _ONLY_LEGAL_FORM.match(line):
            continue
        if _looks_like_a_sentence(line):
            continue
        return line

    return ''


def upsert_contact_from_email(
    *,
    email: str,
    sender_name: str = '',
    body: str = '',
    contact_type: str = 'client',
) -> Tuple[Optional[Contact], bool]:
    """Find, or create, the contact behind an email sender.

    Returns ``(contact, created)``, or ``(None, False)`` for an internal sender.
    A sender is matched on the email address case-insensitively, so the same
    person never gets a second contact because their address was written
    ``Luigi@RossiMax.it`` in one thread and ``luigi@rossimax.it`` in another.

    An existing contact is only ever completed, never corrected: a stored phone
    number, company or name is left exactly as it is.
    """
    address = (email or '').strip().lower()
    if not address or is_internal_email(address):
        return None, False

    person = (sender_name or '').strip()
    # The signature writes the company out in full; the email domain is only a
    # fallback, and is formatted so it reads like a name rather than a hostname.
    company = (
        company_from_signature(body, person)
        or format_company(company_from_email(address))
    )
    phone = phone_from_signature(body)
    contact = Contact.objects.filter(email__iexact=address).first()

    if contact is not None:
        updates = []
        if not contact.phone and phone:
            contact.phone = phone
            updates.append('phone')
        if not contact.company_name and company:
            contact.company_name = company
            updates.append('company_name')
        if not contact.contact_person and person:
            contact.contact_person = person
            updates.append('contact_person')
        if updates:
            contact.save(update_fields=[*updates, 'updated_at'])
        return contact, False

    contact = Contact.objects.create(
        email=address,
        company_name=company or person or address,
        contact_person=person,
        phone=phone,
        type=contact_type,
    )
    return contact, True
