import random
from .config_flow import ConfigFlow


class Configurator:
    def __init__(self):
        super().__init__()
        self.active_flows = {}
        print("Initializing configurator")

    def get_flow(self, flow_id):

        flow = self.active_flows.get(flow_id)

        if not flow:
            self.active_flows[flow_id] = ConfigFlow()

        return self.active_flows.get(flow_id)
