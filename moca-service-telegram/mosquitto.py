import asyncio
import json
import logging
from contextlib import AsyncExitStack
from typing import Dict, Any
import uuid

from asyncio_mqtt import Client, MqttError
from telethon import TelegramClient

from .dispatcher import Dispatchable
from .session_storage import SessionStorage
from .configurator import Configurator


class Mosquitto(Dispatchable):
    def __init__(
        self,
        configurator: Configurator,
        session_storage: SessionStorage,
        options: Dict[str, Any],
    ):
        self._configurator = configurator
        self._session_storage = session_storage

        self.logger = logging.getLogger(self.__class__.__name__)

        self.hostname = options.get("hostname", None)
        self.port = options.get("port", None)
        self.username = options.get("username", None)
        self.password = options.get("password", None)
        self.client_id = options.get("client_id", f"TG{uuid.getnode()}")
        self.reconnect_interval = options.get("reconnect_interval", 3)

        self._mqtt = None

        self.logger.info("Setting up mqtt")

    async def run(self):
        async with Client("localhost") as client:

            await client.subscribe("telegram/#")
            await client.subscribe("debug/#")

            async with client.filtered_messages("telegram/#") as messages:

                async for message in messages:

                    uri = message.topic.split("/")
                    luri = len(uri)

                    # Ignore non telegram messages and responses from self
                    if luri == 0 or uri[0] != "telegram" or uri[luri - 1] == "response":
                        self.logger.info(f"Ignoring [{message.topic}]: {message.payload.decode()}")
                        continue

                    # telegram/users
                    if luri >= 3 and uri[1] == "users":

                        phone = uri[2]

                        if luri == 4 and uri[3] == "get_chats":
                            self.logger.info(f"get_chats [{message.topic}]: {message.payload.decode()}")
                            await self.get_chats(client, phone)
                            continue

                    # telegram/configure
                    if luri >= 3 and uri[1] == "configure":
                        self.logger.info(f"configure [{message.topic}]: {message.payload.decode()}")
                        await self.configure(client, uri[2], message)
                        continue

                    self.logger.warning(f"No handler for [{message.topic}]: {message.payload.decode()}")

    @staticmethod
    async def cancel_tasks(tasks):
        for task in tasks:
            if task.done():
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def configure(self, client, flow_id, message):
        self.logger.debug("Configure telegram service (triggered by mqtt)")
        flow = self._configurator.get_flow(flow_id)

        data = json.loads(message.payload.decode())

        step = await flow.current_step(user_input=data)
        self.logger.debug("Configurator step: %s", flow.current_step.__name__)

        await client.publish(f"{message.topic}/response", json.dumps(step))

    async def get_chats(self, client, phone):

        print("Get chats for user %s (triggered by mqtt)", phone)

        tg: TelegramClient = await self._session_storage.get_session(phone)

        if not await tg.is_user_authorized():
            self.logger.warning("User not authorized")
            return

        chats = []

        for dialog in await tg.get_dialogs():
            chats.append({"title": dialog.title, "chat_id": dialog.id})

        await client.publish(f"telegram/users/{phone}/get_chats/response", json.dumps(chats))

