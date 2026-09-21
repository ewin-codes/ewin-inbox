import re

import requests

# Descriptions Telegram returns for conditions that will read the same way on
# the next attempt. Everything else — network trouble, 429, 5xx — is retried.
NON_RETRIABLE = (
    "bot was blocked by the user",
    "chat not found",
    "user is deactivated",
    "bot can't initiate conversation",
    "unauthorized",
    "forbidden",
    "not enough rights",
)


def redact_token(text):
    """Strip a bot token from any string — Bot API URLs carry it in the path."""
    return re.sub(r"/bot[^/\s]+", "/bot***", str(text))


def escape_html(text):
    """Escape a value for Telegram's HTML parse mode.

    Three characters, exactly the three its documentation names. ``markupsafe``
    would also rewrite quotes as ``&#34;``, which that documentation does not
    mention — and a notification is not the place to find out how the renderer
    feels about it.
    """
    return (str(text if text is not None else "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


class TelegramNotifyError(Exception):
    def __init__(self, code, description, retriable=True):
        self.code = code
        self.description = description
        self.retriable = retriable
        super().__init__(f"[{code}] {description}")


class TelegramNotifyClient:
    """The five Bot API calls this addon needs.

    Deliberately not imported from ``ewin_omnichannel_telegram``: that module
    drives a different bot with a different token, and this one has to install
    on a database where no Telegram connector exists at all.
    """

    def __init__(self, token, api_base_url="https://api.telegram.org", timeout=10):
        self.base = f"{api_base_url.rstrip('/')}/bot{token}"
        self.timeout = timeout

    def _call(self, method, payload=None):
        try:
            response = requests.post(
                f"{self.base}/{method}", data=payload or {}, timeout=self.timeout)
        except requests.RequestException as err:
            # `from None` breaks the implicit __context__ chain: ``err``'s own
            # message usually embeds the full, unredacted request URL, and a
            # traceback logger would print it under "During handling of the
            # above exception" even though redact_token() scrubbed this one.
            raise TelegramNotifyError(
                0, f"Network error: {redact_token(err)}") from None
        data = response.json() if response.content else {}
        if not data.get("ok"):
            description = data.get("description") or f"HTTP {response.status_code}"
            retriable = response.status_code == 429 or not any(
                phrase in description.lower() for phrase in NON_RETRIABLE)
            raise TelegramNotifyError(response.status_code, description, retriable)
        return data["result"]

    def get_me(self):
        return self._call("getMe")

    def set_webhook(self, url, secret):
        return self._call("setWebhook", {
            "url": url, "secret_token": secret, "allowed_updates": '["message"]'})

    def delete_webhook(self):
        return self._call("deleteWebhook")

    def get_webhook_info(self):
        return self._call("getWebhookInfo")

    def send_message(self, chat_id, text):
        return self._call("sendMessage", {
            "chat_id": chat_id, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": True})
