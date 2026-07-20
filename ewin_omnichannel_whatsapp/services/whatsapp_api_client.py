import re
import requests

GRAPH_BASE = "https://graph.facebook.com"

# Meta error codes that must NOT be auto-retried.
NON_RETRIABLE_CODES = {
    131047,  # re-engagement message outside 24h window
    131051,  # unsupported message type outside window
    131026,  # message undeliverable (recipient not opted in / invalid)
    190,     # access token invalid/expired
    100,     # invalid parameter
    132000, 132001, 132005, 132007, 132012, 132015, 132016, 132068, 132069,
    131008,  # required parameter missing
    131009,  # parameter value invalid
}
RETRIABLE_CODES = {130429, 131056, 133016, 368, 80007, 130472}


def _redact_token(text, token):
    text = str(text)
    if token:
        text = text.replace(token, "***")
    return re.sub(r"Bearer\s+[^\s\"']+", "Bearer ***", text)


class WhatsAppApiError(Exception):
    def __init__(self, code, subcode, message, retriable=True):
        self.code = code
        self.subcode = subcode
        self.message = message
        self.description = message  # parity with TelegramApiError.description
        self.retriable = retriable
        super().__init__(f"[{code}/{subcode}] {message}")


class WhatsAppApiClient:
    def __init__(self, token, phone_number_id, waba_id,
                 graph_version="v21.0", timeout=10):
        self.token = token
        self.phone_number_id = phone_number_id
        self.waba_id = waba_id
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
            raise WhatsAppApiError(
                status, 0, f"Non-JSON response (HTTP {status})", True) from None
        if status >= 400 or "error" in data:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            code = err.get("code", status)
            subcode = err.get("error_subcode", 0)
            message = _redact_token(
                err.get("message") or f"HTTP {status}", self.token)
            raise WhatsAppApiError(
                code, subcode, message, self._classify(code, status))
        return data

    def _post(self, path, json=None, files=None, data=None):
        url = f"{self.base}/{path}"
        try:
            resp = requests.post(url, headers=self._headers(), json=json,
                                 files=files, data=data, timeout=self.timeout)
        except requests.RequestException as err:
            raise WhatsAppApiError(
                0, 0, f"Network error: {_redact_token(err, self.token)}", True) from None
        return self._raise_for_error(resp)

    def _get(self, path, params=None):
        url = f"{self.base}/{path}"
        try:
            resp = requests.get(url, headers=self._headers(), params=params,
                                timeout=self.timeout)
        except requests.RequestException as err:
            raise WhatsAppApiError(
                0, 0, f"Network error: {_redact_token(err, self.token)}", True) from None
        return self._raise_for_error(resp)

    # --- connection ---
    def get_phone_number(self):
        return self._get(self.phone_number_id,
                         params={"fields": "display_phone_number,verified_name"})

    # --- messages ---
    def _message(self, payload):
        payload["messaging_product"] = "whatsapp"
        payload["recipient_type"] = "individual"
        return self._post(f"{self.phone_number_id}/messages", json=payload)

    def send_text(self, to, body):
        return self._message({"to": to, "type": "text",
                              "text": {"preview_url": True, "body": body}})

    def send_media(self, to, media_type, media_id, caption=None, filename=None):
        media = {"id": media_id}
        if caption and media_type in ("image", "video", "document"):
            media["caption"] = caption
        if filename and media_type == "document":
            media["filename"] = filename
        return self._message({"to": to, "type": media_type,
                              media_type: media})

    def send_template(self, to, name, language, components):
        return self._message({"to": to, "type": "template", "template": {
            "name": name, "language": {"code": language},
            "components": components}})

    # --- media ---
    def upload_media(self, file_bytes, filename, mime_type):
        files = {"file": (filename, file_bytes,
                          mime_type or "application/octet-stream")}
        data = {"messaging_product": "whatsapp", "type": mime_type or ""}
        res = self._post(f"{self.phone_number_id}/media", files=files, data=data)
        return res.get("id")

    def get_media_url(self, media_id):
        res = self._get(media_id)
        return res.get("url"), res.get("mime_type")

    def download_media(self, url):
        try:
            resp = requests.get(url, headers=self._headers(),
                                timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as err:
            raise WhatsAppApiError(
                0, 0, f"Download error: {_redact_token(err, self.token)}", True) from None
        return resp.content

    # --- templates ---
    def list_templates(self):
        results = []
        params = {"limit": 100, "fields":
                  "name,language,category,status,components"}
        path = f"{self.waba_id}/message_templates"
        while True:
            data = self._get(path, params=params)
            results.extend(data.get("data", []))
            paging = (data.get("paging") or {}).get("cursors") or {}
            after = paging.get("after")
            if not after or not data.get("data"):
                break
            params = dict(params, after=after)
        return results
