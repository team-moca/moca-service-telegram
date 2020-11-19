import logging
from pathlib import Path

from .dispatcher import Dispatchable
from .session_storage import SessionStorage

class Startup(Dispatchable):
    def __init__(self, session_storage: SessionStorage):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._session_storage = session_storage

    async def run(self):
        self.logger.info("Start application...")
        i=0
        for session in Path("sessions").rglob("*.session"):
            await self._session_storage.get_session(session.name[:-8])
            i += 1

        self.logger.info(f"Initialized {i} sessions.")

        return False
