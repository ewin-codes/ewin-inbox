import re
import requests


def _redact_token(text):
    """Strip a Telegram bot token from any string (URLs contain /bot<token>)."""
    return re.sub(r"/bot[^/\s]+", "/bot***", str(text))


# Telegram error descriptions that must NOT be auto-retried.
NON_RETRIABLE = (
    "bot was blocked by the user",
    "chat not found",
    "user is deactivated",
    "bot can't initiate conversation",
    "unauthorized",
    "not enough rights",
)


class TelegramApiError(Exception):
    def __init__(self, code, description, retriable=True):
        self.code = code
        self.description = description
        self.retriable = retriable
        super().__init__(f"[{code}] {description}")


class TelegramApiClient:
    def __init__(self, token, api_base_url="https://api.telegram.org", timeout=10):
        self.token = token
        self.base = f"{api_base_url.rstrip('/')}/bot{token}"
        self.file_base = f"{api_base_url.rstrip('/')}/file/bot{token}"
        self.timeout = timeout

    def _call(self, method, payload=None, files=None):
        url = f"{self.base}/{method}"
        try:
            resp = requests.post(url, data=payload or {}, files=files,
                                 timeout=self.timeout)
        except requests.RequestException as err:
            raise TelegramApiError(0, f"Network error: {_redact_token(err)}", retriable=True)
        data = resp.json() if resp.content else {}
        if not data.get("ok"):
            desc = (data.get("description") or f"HTTP {resp.status_code}").lower()
            retriable = not any(s in desc for s in NON_RETRIABLE)
            if resp.status_code == 429:
                retriable = True
            raise TelegramApiError(resp.status_code, data.get("description", desc),
                                   retriable=retriable)
        return data["result"]

    def get_me(self):
        return self._call("getMe")

    def set_webhook(self, url, secret):
        return self._call("setWebhook", {
            "url": url, "secret_token": secret,
            "allowed_updates": '["message"]'})

    def delete_webhook(self):
        return self._call("deleteWebhook")

    def get_webhook_info(self):
        return self._call("getWebhookInfo")

    def send_message(self, chat_id, text, reply_to=None):
        payload = {"chat_id": chat_id, "text": text}
        if reply_to:
            payload["reply_to_message_id"] = reply_to
        return self._call("sendMessage", payload)

    def send_photo(self, chat_id, file_bytes, filename, caption=None):
        return self._call("sendPhoto", {"chat_id": chat_id, "caption": caption or ""},
                          files={"photo": (filename, file_bytes)})

    def send_document(self, chat_id, file_bytes, filename, caption=None):
        return self._call("sendDocument", {"chat_id": chat_id, "caption": caption or ""},
                          files={"document": (filename, file_bytes)})

    def get_file(self, file_id):
        return self._call("getFile", {"file_id": file_id})

    def download_file(self, file_path):
        url = f"{self.file_base}/{file_path}"
        try:
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as err:
            raise TelegramApiError(0, f"Download error: {_redact_token(err)}", retriable=True)
        return resp.content
