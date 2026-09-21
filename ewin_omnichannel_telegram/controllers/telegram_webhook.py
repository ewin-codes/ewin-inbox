import json
import logging

from odoo import http
from odoo.http import request

from odoo.addons.ewin_omnichannel_core.tools.security import secret_equals

_logger = logging.getLogger(__name__)


class TelegramWebhookController(http.Controller):

    # The channel is part of the path, not a parameter: a converter here would
    # also claim every other channel's .../webhook/<code>/<uuid>, and a payload
    # arriving that way would be handled by this connector — with this
    # connector's secret, which such an account does not have. One route, one
    # channel, the same shape as the other connectors.
    @http.route(
        "/omnichannel/webhook/telegram/<string:account_uuid>",
        type="http", auth="public", csrf=False, methods=["POST"],
        save_session=False)
    def telegram_webhook(self, account_uuid, **kwargs):
        account = request.env["omnichannel.account"].sudo().search([
            ("webhook_uuid", "=", account_uuid),
            ("channel_code", "=", "telegram"),
        ], limit=1)
        if not account or not account.active or account.state == "disabled":
            return request.make_json_response({})  # do not leak existence
        secret = request.httprequest.headers.get(
            "X-Telegram-Bot-Api-Secret-Token") or ""
        stored = account.tg_webhook_secret or ""
        # No stored secret means reject, never "skip the check": the URL is not
        # a credential, and an account whose webhook was registered outside the
        # Register Webhook button would otherwise accept anything. secret_equals
        # answers that, and compares bytes — a non-ASCII byte in the header must
        # read as a mismatch and not as an error page.
        if not secret_equals(secret, stored):
            _logger.warning("Rejected Telegram webhook: bad secret (acct %s)",
                            account.id)
            return request.make_json_response({})
        try:
            payload = json.loads(request.httprequest.get_data() or b"{}")
        except (ValueError, TypeError):
            _logger.warning("Malformed Telegram webhook body (acct %s)",
                            account.id)
            return request.make_json_response({})
        # Process synchronously so the message reaches the operator instantly
        # (a queued-only path added up to one cron tick, ~60s, of latency). Any
        # failure falls back to the retry queue so nothing is lost, and we still
        # return 200 to Telegram. parse_webhook is idempotent via event.record.
        try:
            request.env["omnichannel.connector.telegram"].sudo().parse_webhook(
                account, payload, request.httprequest.headers)
        except Exception:  # noqa: BLE001 - never fail the webhook; queue instead
            _logger.exception(
                "Sync webhook processing failed (acct %s); queuing for retry",
                account.id)
            request.env.cr.rollback()
            request.env["omnichannel.job"].sudo().enqueue(
                model="omnichannel.connector.telegram",
                method="parse_webhook_job",
                args={"account_id": account.id, "payload": payload,
                      "secret": secret},
                company_id=account.company_id.id)
        return request.make_json_response({})
