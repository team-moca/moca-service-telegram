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
        self.logger.info("Run mqtt")
        while True:
            self.logger.error("Loop mqtt")
            try:
                async with AsyncExitStack() as stack:
                    tasks = set()
                    stack.push_async_callback(self.cancel_tasks, tasks)

                    #client = Client(self.hostname, port=self.port, username=self.username, password=self.password,
                    #                client_id=self.client_id)
                    client = Client("localhost")
                    await stack.enter_async_context(client)

                    manager = client.filtered_messages("telegram/configure/+")
                    messages = await stack.enter_async_context(manager)

                    tasks.add(
                        asyncio.create_task(
                            self.configure(client, messages, "telegram/configure/+")
                        )
                    )

                    manager2 = client.filtered_messages("telegram/users/+/get_chats")
                    messages2 = await stack.enter_async_context(manager2)

                    tasks.add(
                        asyncio.create_task(
                            self.get_chats(client, messages2, "telegram/users/+/get_chats")
                        )
                    )

                    # messages = await stack.enter_async_context(client.unfiltered_messages())
                    # task = asyncio.create_task(handle(client, messages, "[unfiltered] {}"))
                    # tasks.add(task)

                    # maybe global mqtt because of scoping?

                    self._mqtt = client

                    await client.subscribe("telegram/#")
                    await asyncio.gather(*tasks)


            except MqttError as error:
                self.logger.error(
                    "Error %s. Reconnecting in %s seconds.", error, self.reconnect_interval
                )
            finally:
                self.logger.info("Finally go to sleep")
                await asyncio.sleep(self.reconnect_interval)

            return True


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

    async def configure(self, client, messages, topic_filter):
        async for message in messages:
            self.logger.debug("Configure telegram service (triggered by mqtt)")
            flow_id = message.topic.split("/")[2]
            flow = self.configurator.get_flow(flow_id)

            data = json.loads(message.payload.decode())

            step = await flow.current_step(user_input=data)
            self.logger.debug("Configurator step: %s", flow.current_step.__name__)

            await client.publish(f"{message.topic}/response", json.dumps(step))

    async def get_chats(self, client, messages, topic_filter):
        async for message in messages:
            phone = message.topic.replace("telegram/users/", "").replace(
                "/get_chats", ""
            )

            self.logger.debug("Get chats for user %s (triggered by mqtt)", phone)

            tg: TelegramClient = await self.session_storage.get_session(phone)

            if not await tg.is_user_authorized():
                self.logger.warning("User not authorized")
                break

            chats = []

            for dialog in await tg.get_dialogs():
                chats.append({"title": dialog.title, "chat_id": dialog.id})

            await client.publish(f"{message.topic}/response", json.dumps(chats))
