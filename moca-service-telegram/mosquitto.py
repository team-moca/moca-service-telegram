import asyncio
import json
import logging
from contextlib import AsyncExitStack
from typing import Dict, Any
import uuid

from asyncio_mqtt import Client, MqttError
from telethon import TelegramClient
from telethon.tl.types import PeerChat, Chat, User, Channel

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
                        self.logger.info(f"Ignoring [{message.topic}]")
                        continue

                    # telegram/users
                    if luri >= 3 and uri[1] == "users":

                        phone = uri[2]

                        if luri == 4 and uri[3] == "get_chats":
                            self.logger.info(
                                f"get_chats [{message.topic}]: {message.payload.decode()}"
                            )
                            await self.get_chats(client, phone)
                            continue

                        elif luri == 4 and uri[3] == "get_contacts":
                            self.logger.info(
                                f"get_contacts [{message.topic}]: {message.payload.decode()}"
                            )
                            await self.get_contacts(client, phone)
                            continue

                        elif luri == 5 and uri[3] == "get_messages":
                            await self.get_messages(client, phone, int(uri[4]))
                            continue

                        elif luri == 5 and uri[3] == "get_contact":
                            await self.get_contact(client, phone, int(uri[4]))
                            continue

                    # telegram/configure
                    if luri >= 3 and uri[1] == "configure":
                        self.logger.info(
                            f"configure [{message.topic}]: {message.payload.decode()}"
                        )
                        await self.configure(client, uri[2], message)
                        continue

                    self.logger.warning(
                        f"No handler for [{message.topic}]: {message.payload.decode()}"
                    )

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

        self.logger.info("Get chats for user %s (triggered by mqtt)", phone)

        tg: TelegramClient = await self._session_storage.get_session(phone)

        if not await tg.is_user_authorized():
            self.logger.warning("User not authorized")
            return

        chats = []

        for dialog in await tg.get_dialogs():

            self.logger.info(f"Found dialog \"{dialog.title}\"")

            last_message = {
                "message_id": dialog.message.id,
                "contact_id": dialog.message.sender_id,
                "chat_id": dialog.id,
                "sent_datetime": dialog.message.date.isoformat(),
                "message": {
                    "type": "text" if dialog.message.message else "unsupported",
                    "content": dialog.message.text,
                },
            }

            chats.append(
                {
                    "name": dialog.title,
                    "chat_id": dialog.id,
                    "chat_type": "ChatType.group" if dialog.is_group else "ChatType.single",
                    "last_message": last_message,
                }
            )

        await client.publish(
            f"telegram/users/{phone}/get_chats/response", json.dumps(chats)
        )

    @staticmethod
    def convert_tg_message_to_message(tg_message):
        return {
            "message_id": tg_message.id,
            "contact_id": tg_message.sender_id,
            "chat_id": tg_message.chat_id,
            "sent_datetime": tg_message.date.isoformat(),
            "message": {
                "type": "text" if tg_message.message else "unsupported",
                "content": tg_message.text,
            },
        }

    async def get_messages(self, client, phone: str, chat_id: int):
        """Get a single chat for a user by chat_id."""

        self.logger.info("Get chat %s for user %s (triggered by mqtt)", chat_id, phone)

        tg: TelegramClient = await self._session_storage.get_session(phone)

        if not await tg.is_user_authorized():
            self.logger.warning("User not authorized")
            return

        chat: Chat = await tg.get_entity(chat_id)

        messages = await tg.get_messages(chat, 25)

        await client.publish(
            f"telegram/users/{phone}/get_messages/{chat_id}/response",
            json.dumps(
                [self.convert_tg_message_to_message(tg_message) for tg_message in messages]
            ),
        )

    async def get_contact(self, client, phone: str, contact_id: int):
        """Get a single contact of a user by chat_id."""

        self.logger.info("Get contact %s for user %s (triggered by mqtt)", contact_id, phone)

        tg: TelegramClient = await self._session_storage.get_session(phone)

        if not await tg.is_user_authorized():
            self.logger.warning("User not authorized")
            return

        user_or_channel = await tg.get_entity(contact_id)

        contact = {}

        if type(user_or_channel) is User:
            contact = {
                "contact_id": user_or_channel.id,
                "name": f"{user_or_channel.first_name} {user_or_channel.last_name}",
                "username": user_or_channel.username,
                "phone": f"+{user_or_channel.phone}",
            }
        elif type(user_or_channel) is Channel:
            contact = {
                "contact_id": contact_id,
                "name": user_or_channel.username,
                "username": user_or_channel.username,
                "phone": None,
            }
        else:
            pass

        await client.publish(
            f"telegram/users/{phone}/get_contact/{contact_id}/response",
            json.dumps(
                contact
            ),
        )
