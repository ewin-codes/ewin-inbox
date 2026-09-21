import json
import logging

from odoo import http
from odoo.http import request

from odoo.addons.ewin_omnichannel_core.tools.security import secret_equals

_logger = logging.getLogger(__name__)


class MessengerWebhookController(http.Controller):

    def _account(self, account_uuid):
        return request.env["omnichannel.account"].sudo().search([
            ("webhook_uuid", "=", account_uuid),
            ("channel_code", "=", "messenger"),
        ], limit=1)

    @http.route(
        "/omnichannel/webhook/messenger/<string:account_uuid>",
        type="http", auth="public", csrf=False, methods=["GET"],
        save_session=False)
    def messenger_verify(self, account_uuid, **kwargs):
        """Meta's subscription handshake: echo hub.challenge when the verify
        token matches, otherwise 403."""
        account = self._account(account_uuid)
        mode = kwargs.get("hub.mode")
        token = kwargs.get("hub.verify_token") or ""
        challenge = kwargs.get("hub.challenge") or ""
        if (account and mode == "subscribe"
                and secret_equals(token, account.mg_verify_token or "")):
            return request.make_response(challenge)
        return request.make_response("", status=403)

    @http.route(
        "/omnichannel/webhook/messenger/<string:account_uuid>",
        type="http", auth="public", csrf=False, methods=["POST"],
        save_session=False)
    def messenger_webhook(self, account_uuid, **kwargs):
        account = self._account(account_uuid)
        if not account or not account.active or account.state == "disabled":
            return request.make_json_response({})  # do not leak existence
        raw = request.httprequest.get_data() or b"{}"
        connector = request.env["omnichannel.connector.messenger"].sudo()
        if not connector._verify_signature(
                account, raw, request.httprequest.headers):
            _logger.warning("Rejected Messenger webhook: bad signature "
                            "(acct %s)", account.id)
            return request.make_json_response({})
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            _logger.warning("Malformed Messenger webhook body (acct %s)",
                            account.id)
            return request.make_json_response({})
        try:
            connector.parse_webhook(account, payload,
                                    request.httprequest.headers)
        except Exception:  # noqa: BLE001 - never fail the webhook; queue instead
            _logger.exception(
                "Sync Messenger webhook failed (acct %s); queuing for retry",
                account.id)
            request.env.cr.rollback()
            request.env["omnichannel.job"].sudo().enqueue(
                model="omnichannel.connector.messenger",
                method="parse_webhook_job",
                args={"account_id": account.id, "payload": payload,
                      "signature": request.httprequest.headers.get(
                          "X-Hub-Signature-256", "")},
                company_id=account.company_id.id)
        return request.make_json_response({})
