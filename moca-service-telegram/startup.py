import logging
from pathlib import Path

from .dispatcher import Dispatchable
from .session_storage import SessionStorage
from .mosquitto import Mosquitto

class Startup(Dispatchable):
    def __init__(self, session_storage: SessionStorage, mqtt: Mosquitto):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._session_storage = session_storage
        self._mqtt = mqtt

    async def run(self):
        self.logger.info("Start application...")
        i=0
        for session_name in Path("sessions").rglob("*.session"):
            session = await self._session_storage.get_session(int(session_name.name[:-8]))
            await session.start()
            #await self._mqtt.load_missed()
            i += 1

        self.logger.info(f"Initialized {i} sessions.")
        return True
