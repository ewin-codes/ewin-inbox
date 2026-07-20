import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WhatsAppWebhookController(http.Controller):

    def _account(self, account_uuid):
        return request.env["omnichannel.account"].sudo().search([
            ("webhook_uuid", "=", account_uuid),
            ("channel_code", "=", "whatsapp"),
        ], limit=1)

    @http.route(
        "/omnichannel/webhook/whatsapp/<string:account_uuid>",
        type="http", auth="public", csrf=False, methods=["GET"],
        save_session=False)
    def whatsapp_verify(self, account_uuid, **kwargs):
        account = self._account(account_uuid)
        mode = kwargs.get("hub.mode")
        token = kwargs.get("hub.verify_token") or ""
        challenge = kwargs.get("hub.challenge") or ""
        if (account and mode == "subscribe" and account.wa_verify_token
                and hmac.compare_digest(token, account.wa_verify_token)):
            return request.make_response(challenge)
        return request.make_response("", status=403)

    @http.route(
        "/omnichannel/webhook/whatsapp/<string:account_uuid>",
        type="http", auth="public", csrf=False, methods=["POST"],
        save_session=False)
    def whatsapp_webhook(self, account_uuid, **kwargs):
        account = self._account(account_uuid)
        if not account or not account.active or account.state == "disabled":
            return request.make_json_response({})  # do not leak existence
        raw = request.httprequest.get_data() or b"{}"
        connector = request.env["omnichannel.connector.whatsapp"].sudo()
        if not connector._verify_signature(
                account, raw, request.httprequest.headers):
            _logger.warning("Rejected WhatsApp webhook: bad signature "
                            "(acct %s)", account.id)
            return request.make_json_response({})
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            _logger.warning("Malformed WhatsApp webhook body (acct %s)",
                            account.id)
            return request.make_json_response({})
        try:
            connector.parse_webhook(account, payload,
                                    request.httprequest.headers)
        except Exception:  # noqa: BLE001 - never fail the webhook; queue instead
            _logger.exception(
                "Sync WhatsApp webhook failed (acct %s); queuing for retry",
                account.id)
            request.env.cr.rollback()
            request.env["omnichannel.job"].sudo().enqueue(
                model="omnichannel.connector.whatsapp",
                method="parse_webhook_job",
                args={"account_id": account.id, "payload": payload,
                      "signature": request.httprequest.headers.get(
                          "X-Hub-Signature-256", "")},
                company_id=account.company_id.id)
        return request.make_json_response({})
