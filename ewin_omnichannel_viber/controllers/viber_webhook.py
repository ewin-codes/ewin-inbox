import hashlib
import hmac
import json
import logging

from odoo import http
from odoo.http import request

from odoo.addons.ewin_omnichannel_core.tools.security import secret_equals

_logger = logging.getLogger(__name__)


class ViberWebhookController(http.Controller):

    @http.route(
        "/omnichannel/viber/webhook/<string:account_uuid>",
        type="http", auth="public", csrf=False, methods=["POST"],
        save_session=False)
    def viber_webhook(self, account_uuid, **kwargs):
        account = request.env["omnichannel.account"].sudo().search([
            ("webhook_uuid", "=", account_uuid),
            ("channel_code", "=", "viber"),
        ], limit=1)
        if not account or not account.active or account.state == "disabled":
            return request.make_json_response({})  # do not leak existence
        raw_body = request.httprequest.get_data() or b"{}"
        token = account.viber_auth_token or ""
        # Viber signs every callback: X-Viber-Content-Signature is the
        # HMAC-SHA256 of the raw request body keyed by the account auth token.
        signature = request.httprequest.headers.get(
            "X-Viber-Content-Signature") or ""
        # No token means no key to verify against, which is a reason to refuse
        # rather than to accept the callback unsigned.
        expected = hmac.new(
            token.encode(), raw_body, hashlib.sha256).hexdigest() if token else ""
        if not secret_equals(signature, expected):
            _logger.warning(
                "Rejected Viber webhook: bad signature (acct %s)", account.id)
            return request.make_json_response({})
        try:
            payload = json.loads(raw_body)
        except (ValueError, TypeError):
            _logger.warning("Malformed Viber webhook body (acct %s)", account.id)
            return request.make_json_response({})
        # Process synchronously so the message reaches the operator instantly.
        # Any failure falls back to the retry queue so nothing is lost, and we
        # still return 200 to Viber. parse_webhook is idempotent via event.record.
        try:
            request.env["omnichannel.connector.viber"].sudo().parse_webhook(
                account, payload, request.httprequest.headers)
        except Exception:  # noqa: BLE001 - never fail the webhook; queue instead
            _logger.exception(
                "Sync Viber webhook processing failed (acct %s); queuing",
                account.id)
            request.env.cr.rollback()
            request.env["omnichannel.job"].sudo().enqueue(
                model="omnichannel.connector.viber",
                method="parse_webhook_job",
                args={"account_id": account.id, "payload": payload},
                company_id=account.company_id.id)
        return request.make_json_response({})
