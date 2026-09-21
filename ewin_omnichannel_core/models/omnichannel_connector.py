from odoo import api, models


class OmnichannelConnector(models.AbstractModel):
    _name = "omnichannel.connector"
    _description = "Omnichannel Connector Contract"

    # The one method the job queue may call on a connector. A webhook that
    # cannot be processed in its own request is retried through the queue,
    # which runs as superuser — so the entry point is published here by name
    # rather than every connector method being reachable by default.
    # See omnichannel.job._resolve_target.
    _job_methods = frozenset({"parse_webhook_job"})

    def validate_configuration(self, account):
        raise NotImplementedError

    def connect(self, account):
        raise NotImplementedError

    def disconnect(self, account):
        raise NotImplementedError

    def register_webhook(self, account):
        raise NotImplementedError

    def remove_webhook(self, account):
        raise NotImplementedError

    def parse_webhook(self, account, payload, headers):
        """Return a list of normalized event dicts (universal format)."""
        raise NotImplementedError

    def normalize_incoming_message(self, account, provider_event):
        raise NotImplementedError

    def send_message(self, account, message):
        raise NotImplementedError

    def send_attachment(self, account, message, attachment):
        raise NotImplementedError

    def download_attachment(self, account, provider_attachment):
        raise NotImplementedError

    def get_external_profile(self, account, external_user_id):
        raise NotImplementedError

    def handle_provider_error(self, account, error):
        raise NotImplementedError

    @api.model
    def _notify_ui(self, message, kind="success"):
        """A toast on the account form, and how a button answers.

        A provider failure is reported this way and never by raising. The
        failure path records what went wrong on the account - the error
        state, ``last_error``, a journal row - and Odoo commits a request
        only when it returns successfully, so raising rolls that record
        away with the rest of the request: the user reads the message and
        the form behind it comes back looking untouched by it. A danger
        toast says the same sentence and lets the write land, and it is
        sticky because a failure should not disappear on its own.

        A ``UserError`` stays right for what the user must fix *before*
        anything is attempted - a credential that is not set, a setting
        that is refused - because nothing has been written at that point.
        """
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"message": message, "type": kind,
                       "sticky": kind != "success"},
        }
