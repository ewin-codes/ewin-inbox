import requests

# Viber send_message status codes that must NOT be auto-retried (permanent).
# 0 = ok; 12 = tooManyRequests (retriable); everything else here is terminal.
NON_RETRIABLE_STATUSES = frozenset(
    {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14,
     15, 16, 17, 18, 19, 20, 21, 22, 23, 24})


class ViberApiError(Exception):
    def __init__(self, code, description, retriable=True):
        self.code = code
        self.description = description
        self.retriable = retriable
        super().__init__(f"[{code}] {description}")


class ViberApiClient:
    """Thin wrapper over the Viber REST bot API (https://chatapi.viber.com/pa).

    Auth is a single account token passed in the X-Viber-Auth-Token header.
    Every call returns a JSON body with a numeric ``status`` (0 = ok)."""

    def __init__(self, token, api_base_url="https://chatapi.viber.com/pa",
                 timeout=10):
        self.token = token
        self.base = api_base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self):
        return {"X-Viber-Auth-Token": self.token}

    def _call(self, method, payload=None):
        url = f"{self.base}/{method}"
        try:
            resp = requests.post(url, json=payload or {},
                                 headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as err:
            raise ViberApiError(0, f"Network error: {err}", retriable=True)
        data = resp.json() if resp.content else {}
        status = data.get("status")
        if status != 0:
            message = data.get("status_message") or f"HTTP {resp.status_code}"
            retriable = status not in NON_RETRIABLE_STATUSES
            if resp.status_code == 429 or status == 12:
                retriable = True
            raise ViberApiError(status if status is not None else resp.status_code,
                                message, retriable=retriable)
        return data

    def get_account_info(self):
        return self._call("get_account_info", {})

    def set_webhook(self, url, event_types=None):
        payload = {"url": url}
        if event_types is not None:
            payload["event_types"] = event_types
        return self._call("set_webhook", payload)

    def remove_webhook(self):
        # Viber removes the webhook when set_webhook is called with an empty url.
        return self._call("set_webhook", {"url": ""})

    def send_message(self, payload):
        return self._call("send_message", payload)

    def download_media(self, media_url):
        """Fetch inbound media. Viber serves media on a temporary public URL,
        so no auth header is needed. Returns the raw bytes."""
        try:
            resp = requests.get(media_url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as err:
            raise ViberApiError(0, f"Download error: {err}", retriable=True)
        return resp.content
