import random
from .config_flow import ConfigFlow
import logging

_LOGGER = logging.getLogger(__name__)


class Configurator:
    def __init__(self, session_storage):
        super().__init__()
        self.session_storage = session_storage
        self.active_flows = {}
        _LOGGER.info("Starting configurator")

    def get_flow(self, flow_id):

        flow = self.active_flows.get(flow_id)

        if not flow:
            self.active_flows[flow_id] = ConfigFlow(self.session_storage)

        return self.active_flows.get(flow_id)
