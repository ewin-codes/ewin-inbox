import json
import re

import requests

GRAPH_BASE = "https://graph.facebook.com"

# Graph/Messenger error codes that must NOT be auto-retried: they are terminal
# for this message and retrying only burns quota.
NON_RETRIABLE_CODES = {
    10,    # policy/permission — e.g. message sent outside the 24h window
    100,   # invalid parameter (bad recipient, malformed request)
    190,   # access token invalid or expired
    200,   # app lacks permission to message this user
    551,   # recipient is unavailable / cannot receive messages
}
# Transient conditions worth retrying regardless of the HTTP status.
RETRIABLE_CODES = {
    1,     # unknown/temporary API error
    2,     # service temporarily unavailable
    4,     # application-level rate limit
    368,   # temporarily blocked for policy reasons
    613,   # calls to this API are rate limited
}


def _redact_token(text, token):
    """Strip the page access token (and any Bearer credential) from a string."""
    text = str(text)
    if token:
        text = text.replace(token, "***")
    return re.sub(r"Bearer\s+[^\s\"']+", "Bearer ***", text)


class MessengerApiError(Exception):
    def __init__(self, code, subcode, message, retriable=True):
        self.code = code
        self.subcode = subcode
        self.message = message
        self.description = message  # parity with the other connectors' errors
        self.retriable = retriable
        super().__init__(f"[{code}/{subcode}] {message}")


class MessengerApiClient:
    """Thin wrapper over the Facebook Graph API for a single Messenger Page.

    All calls authenticate with the Page access token via a Bearer header so
    the credential never lands in a URL (and therefore never in an access log
    or an exception message). Every Graph error is classified as retriable or
    terminal so the job queue only retries what can succeed on a second try.
    """

    def __init__(self, token, page_id, graph_version="v21.0", timeout=10):
        self.token = token
        self.page_id = page_id
        self.base = f"{GRAPH_BASE}/{graph_version}"
        self.timeout = timeout

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def _classify(self, code, status):
        if code in NON_RETRIABLE_CODES:
            return False
        if code in RETRIABLE_CODES:
            return True
        if status == 429 or (status is not None and 500 <= status < 600):
            return True
        # default: 4xx client errors are terminal, everything else retriable
        return not (status is not None and 400 <= status < 500)

    def _raise_for_error(self, resp):
        status = resp.status_code
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            raise MessengerApiError(
                status, 0, f"Non-JSON response (HTTP {status})", True) from None
        if status >= 400 or (isinstance(data, dict) and "error" in data):
            err = data.get("error", {}) if isinstance(data, dict) else {}
            code = err.get("code", status)
            subcode = err.get("error_subcode", 0)
            message = _redact_token(
                err.get("message") or f"HTTP {status}", self.token)
            raise MessengerApiError(
                code, subcode, message, self._classify(code, status))
        return data

    def _get(self, path, params=None):
        url = f"{self.base}/{path}"
        try:
            resp = requests.get(url, headers=self._headers(), params=params,
                                timeout=self.timeout)
        except requests.RequestException as err:
            raise MessengerApiError(
                0, 0, f"Network error: {_redact_token(err, self.token)}",
                True) from None
        return self._raise_for_error(resp)

    def _post(self, path, json_body=None, data=None, files=None):
        url = f"{self.base}/{path}"
        try:
            resp = requests.post(url, headers=self._headers(), json=json_body,
                                 data=data, files=files, timeout=self.timeout)
        except requests.RequestException as err:
            raise MessengerApiError(
                0, 0, f"Network error: {_redact_token(err, self.token)}",
                True) from None
        return self._raise_for_error(resp)

    # --- connection / profile ---
    def get_page(self):
        return self._get(self.page_id, params={"fields": "name"})

    def get_user_profile(self, psid):
        return self._get(psid, params={
            "fields": "first_name,last_name,profile_pic"})

    # --- outbound messages ---
    def _recipient_message(self, recipient_id, message, messaging_type, tag):
        payload = {
            "recipient": {"id": recipient_id},
            "messaging_type": messaging_type,
            "message": message,
        }
        if tag:
            payload["messaging_type"] = "MESSAGE_TAG"
            payload["tag"] = tag
        return payload

    def send_text(self, recipient_id, text, messaging_type="RESPONSE", tag=None):
        payload = self._recipient_message(
            recipient_id, {"text": text}, messaging_type, tag)
        return self._post("me/messages", json_body=payload)

    def send_attachment(self, recipient_id, attachment_type, file_bytes,
                        filename, mime_type, messaging_type="RESPONSE",
                        tag=None):
        """Upload a local file and attach it to a Send API message.

        The Send API takes multipart form data: the ``recipient`` and
        ``message`` parts are JSON strings and ``filedata`` carries the bytes.
        ``is_reusable`` is False because each attachment belongs to a single
        conversation.
        """
        message = {"attachment": {
            "type": attachment_type, "payload": {"is_reusable": False}}}
        data = {
            "recipient": json.dumps({"id": recipient_id}),
            "message": json.dumps(message),
            "messaging_type": messaging_type,
        }
        if tag:
            data["messaging_type"] = "MESSAGE_TAG"
            data["tag"] = tag
        files = {"filedata": (
            filename, file_bytes, mime_type or "application/octet-stream")}
        return self._post("me/messages", data=data, files=files)

    # --- media ---
    def download(self, url):
        """Fetch an inbound attachment from its (pre-signed) CDN URL.

        Returns ``(bytes, content_type)``; the content type comes from the
        response headers because the webhook payload does not carry a mime.
        """
        try:
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as err:
            raise MessengerApiError(
                0, 0, f"Download error: {_redact_token(err, self.token)}",
                True) from None
        content_type = (resp.headers.get("Content-Type") or "").split(";")[0]
        return resp.content, content_type or None
