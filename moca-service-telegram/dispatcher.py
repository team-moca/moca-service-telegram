import asyncio
import logging
import signal
from typing import List


class Dispatchable:
    def __init__(self):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)

    async def run(self):
        raise NotImplementedError()


class Dispatcher:
    def __init__(self, dispatchables: Dispatchable):
        self._dispatchables = dispatchables
        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self._stopping = False
        self._tasks: List[asyncio.Task] = []

    def run(self) -> None:
        asyncio.run(self.start())

    async def start(self) -> None:
        self._logger.info("Starting up")

        for dispatchable in self._dispatchables:
            self._tasks.append(
                asyncio.create_task(self.run_task(dispatchable)),
            )

        try:
            asyncio.get_event_loop().add_signal_handler(signal.SIGTERM, self.stop)
            asyncio.get_event_loop().add_signal_handler(signal.SIGINT, self.stop)
        except NotImplementedError:
            pass # Ignore if not implemented. Means this program is running in windows, which has no signals.

        await asyncio.gather(*self._tasks, return_exceptions=True)

        self.stop()

    def stop(self) -> None:
        if self._stopping:
            return

        self._stopping = True

        self._logger.info("Shutting down")
        for task, dispatchable in zip(self._tasks, self._dispatchables):
            task.cancel()
        self._dispatchables.clear()
        self._logger.info("Shutdown finished successfully")

    async def run_task(self, dispatchable):
        while True:
            try:
                if not await dispatchable.run():
                    break
            except asyncio.CancelledError:
                self._logger.info(f"Asyncio cancelled {dispatchable.__name__}")
                break
            # except Exception:
            #     dispatchable.logger.exception("Error executing dispatchable.")
