import asyncio
import json
import logging
from contextlib import AsyncExitStack
from typing import Dict, Any
import uuid

from asyncio_mqtt import Client, MqttError
from telethon import TelegramClient
from telethon.tl.types import Message, PeerChat, Chat, User, Channel

from .dispatcher import Dispatchable
from .session_storage import SessionStorage
from .configurator import ConfigFlow, Configurator


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

        self._session_storage.callbacks.append(self.handle_event)

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

                        connector_id = uri[2]

                        if luri == 4 and uri[3] == "get_chats":
                            self.logger.info(
                                f"get_chats [{message.topic}]: {message.payload.decode()}"
                            )
                            await self.get_chats(client, connector_id)
                            continue

                        elif luri == 4 and uri[3] == "get_contacts":
                            self.logger.info(
                                f"get_contacts [{message.topic}]: {message.payload.decode()}"
                            )
                            await self.get_contacts(client, connector_id)
                            continue

                        elif luri == 4 and uri[3] == "send_message":
                            self.logger.info(
                                f"send_message [{message.topic}]: {message.payload.decode()}"
                            )
                            await self.send_message(client, connector_id, json.loads(message.payload.decode()))
                            continue

                        elif luri == 4 and uri[3] == "delete":
                            self.logger.info(
                                f"delete [{message.topic}]: {message.payload.decode()}"
                            )
                            await self.delete(client, connector_id)
                            continue

                        elif luri == 5 and uri[3] == "get_messages":
                            await self.get_messages(client, connector_id, int(uri[4]))
                            continue

                        elif luri == 5 and uri[3] == "get_contact":
                            await self.get_contact(client, connector_id, int(uri[4]))
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
        flow: ConfigFlow = self._configurator.get_flow(flow_id)

        data = json.loads(message.payload.decode())

        step = await flow.current_step(user_input=data)
        self.logger.debug("Configurator step: %s", flow.current_step.__name__)

        await client.publish(f"{message.topic}/response", json.dumps(step))

        if step.get("step") == "finished":

            # Send all chats now to moca
            await self.get_chats(client, flow_id)

    async def get_chats(self, client, connector_id):

        self.logger.info("Get chats for connector %s (triggered by mqtt)", connector_id)

        tg: TelegramClient = await self._session_storage.get_session(connector_id)

        if not await tg.is_user_authorized():
            self.logger.warning("User not authorized")
            return

        me_id = (await tg.get_me()).id

        chats = []

        for dialog in await tg.get_dialogs():

            self.logger.info(f"Found dialog \"{dialog.title}\"")

            participants = []

            if dialog.is_group:
                participants = [participant.id for participant in await tg.get_participants(dialog)]
            else:
                participants = list(set([dialog.id, me_id]))

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
                    "participants": participants
                }
            )

        await client.publish(
            f"moca/via/telegram/{connector_id}/chats", json.dumps(chats)
        )

    @staticmethod
    async def convert_tg_message_to_message(tg_message: Message, connector_id):

        print(tg_message)

        message = {}

        if tg_message.photo:
            path = await tg_message.download_media(f"../moca-server/storage/{str(uuid.uuid4())}")
            print('Image saved to', path)  # printed after download is done

            message = {
                "type": "image",
                "url": path.replace("../moca-server/storage/", ""),
                "content": tg_message.text,
            }

        elif tg_message.audio:
            path = await tg_message.download_media(f"../moca-server/storage/{str(uuid.uuid4())}")
            print('audio saved to', path)  # printed after download is done

            message = {
                "type": "audio",
                "url": path.replace("../moca-server/storage/", ""),
                "content": tg_message.text,
            }

        elif tg_message.voice:
            path = await tg_message.download_media(f"../moca-server/storage/{str(uuid.uuid4())}")
            print('voice saved to', path)  # printed after download is done

            message = {
                "type": "voice",
                "url": path.replace("../moca-server/storage/", ""),
                "content": tg_message.text,
            }

        elif tg_message.video or tg_message.video_note:
            path = await tg_message.download_media(f"../moca-server/storage/{str(uuid.uuid4())}")
            print('video saved to', path)  # printed after download is done

            message = {
                "type": "video",
                "url": path.replace("../moca-server/storage/", ""),
                "content": tg_message.text,
            }

        elif tg_message.gif:
            path = await tg_message.download_media(f"../moca-server/storage/{str(uuid.uuid4())}")
            print('gif saved to', path)  # printed after download is done

            message = {
                "type": "gif",
                "url": path.replace("../moca-server/storage/", ""),
                "content": tg_message.text,
            }

        elif tg_message.document:
            path = await tg_message.download_media(f"../moca-server/storage/{str(uuid.uuid4())}")
            print('Document saved to', path)  # printed after download is done

            message = {
                "type": "document",
                "url": path.replace("../moca-server/storage/", ""),
                "content": tg_message.text,
            }

        elif tg_message.contact:
            message = {
                "type": "contact",
                "content": tg_message.contact.vcard,
            }

        elif tg_message.geo:
            message = {
                "type": "geo",
                "geo_point": {
                    "lon": tg_message.geo.long,
                    "lat": tg_message.geo.lat
                }
            }

        elif tg_message.dice:
            # Convert dice messages to a string: "🎲 (2)"

            message = {
                "type": "text",
                "content": f"{tg_message.dice.emoticon} ({tg_message.dice.value})"
            }

        elif tg_message.message:
            message = {
                "type": "text",
                "content": tg_message.text,
            }

        else:
            message = {
                "type": "unsupported",
            }

        return {
            "message_id": tg_message.id,
            "contact_id": tg_message.sender_id,
            "chat_id": tg_message.chat_id,
            "sent_datetime": tg_message.date.isoformat(),
            "message": message
        }

    async def handle_event(self, connector_id, event):
        async with Client("localhost") as client:
            await client.publish(
                f"moca/via/telegram/{connector_id}/messages",
                json.dumps(
                    [await self.convert_tg_message_to_message(event.message, connector_id)]
                ),
            )

    async def get_messages(self, client, connector_id: str, chat_id: int):
        """Get a single chat for a user by chat_id."""

        self.logger.info("Get chat %s for user %s (triggered by mqtt)", chat_id, connector_id)

        tg: TelegramClient = await self._session_storage.get_session(connector_id)

        if not await tg.is_user_authorized():
            self.logger.warning("User not authorized")
            return

        chat: Chat = await tg.get_entity(chat_id)

        messages = await tg.get_messages(chat, 25)

        await client.publish(
            f"telegram/users/{connector_id}/get_messages/{chat_id}/response",
            json.dumps(
                [await self.convert_tg_message_to_message(tg_message, connector_id) for tg_message in messages]
            ),
        )

    async def get_contact(self, client, connector_id: str, contact_id: int):
        """Get a single contact of a user by chat_id."""

        self.logger.info("Get contact %s for user %s (triggered by mqtt)", contact_id, connector_id)

        tg: TelegramClient = await self._session_storage.get_session(connector_id)

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
            f"telegram/users/{connector_id}/get_contact/{contact_id}/response",
            json.dumps(
                contact
            ),
        )


    async def delete(self, client, connector_id: str):
        """Delete a connector."""

        self.logger.info("Delete connector %s (triggered by mqtt)", connector_id)

        tg: TelegramClient = await self._session_storage.get_session(connector_id)

        if tg:

            if not await tg.is_user_authorized():
                self.logger.warning("User not authorized")
                return

            await tg.disconnect()
            await self._session_storage.delete_session(connector_id)

        await client.publish(
            f"telegram/users/{connector_id}/delete/response",
            json.dumps(
                {"success": True}
            ),
        )

    async def send_message(self, client, connector_id: str, message: Dict):
        """Send a message."""

        self.logger.info("Send message via %s (triggered by mqtt)", connector_id)

        print(message)

        tg: TelegramClient = await self._session_storage.get_session(connector_id)

        if tg:

            if not await tg.is_user_authorized():
                self.logger.warning("User not authorized")
                return

            content = message.get("message")
            chat_id = message.get("chat_id")

            if content and chat_id:
                content_type = content.get("type")
                content_content = content.get("content")

                if content_type == "text" and content:
                    sent = await tg.send_message(chat_id, content_content)

                    await client.publish(
                        f"telegram/users/{connector_id}/send_message/response",
                        json.dumps(
                            self.convert_tg_message_to_message(sent, connector_id)
                        ),
                    )