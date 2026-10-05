from connectors.files import load_yaml
from connectors.google_ads import Connector as AdExportConnector


class Connector(AdExportConnector):
    """Reads Meta Ads Manager CSV exports from data_inbox/meta_ads/.

    Same logic and metrics as google_ads, with its own folder, source name, and config/meta_ads.yaml.
    """

    name = "meta_ads"

    def __init__(self, config=None):
        super().__init__(config if config is not None else load_yaml("meta_ads.yaml"))
