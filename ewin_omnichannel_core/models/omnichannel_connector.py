from odoo import models


class OmnichannelConnector(models.AbstractModel):
    _name = "omnichannel.connector"
    _description = "Omnichannel Connector Contract"

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
