"""Comparisons whose failure mode must not tell a caller anything.

Plain Python, no Odoo environment: a webhook controller reaches for this
before it has decided whether the caller may exist at all.
"""

import hmac


def secret_equals(presented, expected):
    """Compare a caller-presented secret against the expected value.

    Both arguments are ``str``: one arrives from an HTTP header or a query
    string, the other is a stored secret or a signature computed from the
    request body. The comparison runs on their UTF-8 bytes, and that is the
    whole point of routing every call site through here.

    ``hmac.compare_digest`` raises ``TypeError`` when a ``str`` argument
    holds a character outside ASCII, and WSGI hands header values through
    decoded as Latin-1 — so any caller can put one there, and a query string
    carries whatever the caller likes. Compared as ``str``, a single crafted
    byte would raise instead of returning ``False``, and the route would
    answer that exception differently from an ordinary mismatch: an error
    page where a rejection is a plain ``200`` or a ``403``. That difference
    is an oracle. It tells an unauthenticated caller that this account UUID
    exists and has a secret configured — precisely what the uniform
    rejection exists to hide.

    An empty ``expected`` means there is nothing to verify against, which is
    a reason to refuse rather than to wave the request through: a URL is not
    a credential. Every connector fails closed this way, so the rule lives
    here instead of in each of them.
    """
    if not expected:
        return False
    return hmac.compare_digest(presented.encode(), expected.encode())
