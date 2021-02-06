import base64
import asyncio
import json
import logging
from contextlib import AsyncExitStack
from typing import Dict, Any
import uuid

from asyncio_mqtt import Client, MqttError
from telethon import TelegramClient
from telethon.tl.types import Message, PeerChannel, PeerChat, Chat, PeerUser, User, Channel

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
                    if luri == 0 or uri[0] != "telegram" or uri[luri - 1] == "response" or luri < 4:
                        self.logger.info(f"Ignoring [{message.topic}]")
                        continue

                    # {service_type}/{connector_id}/{uuid}/{command}
                    connector_id = int(uri[1])
                    cmd = uri[3]

                    if cmd == "get_chats":
                        self.logger.info(
                            f"get_chats [{message.topic}]: {message.payload.decode()}"
                        )
                        await self.get_chats(client, connector_id)
                        continue

                    elif cmd == "send_message":
                        self.logger.info(
                            f"send_message [{message.topic}]: {message.payload.decode()}"
                        )
                        await self.send_message(client, connector_id, json.loads(message.payload.decode()), f"{message.topic}/response")
                        continue

                    elif cmd == "configure":
                        self.logger.info(
                            f"configure [{message.topic}]: {message.payload.decode()}"
                        )
                        await self.configure(client, connector_id, message)
                        continue

                    elif cmd == "delete_connector":
                        self.logger.warning(
                            f"delete [{message.topic}]: {message.payload.decode()}"
                        )
                        await self.delete(client, connector_id, f"{message.topic}/response")
                        continue

                    elif luri == 5 and cmd == "get_messages":
                        await self.get_messages(client, connector_id, int(uri[4]), f"{message.topic}/response")
                        continue

                    elif luri == 5 and cmd == "get_contact":
                        await self.get_contact(client, connector_id, int(uri[4]), f"{message.topic}/response")
                        continue

                    elif luri == 5 and cmd == "get_media":
                        await self.get_media(client, connector_id, uri[4], f"{message.topic}/response")
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

    async def load_missed(self):
        async with Client("localhost") as client:
            # Load messages that were send while the connector was offline
            for connector_id_str in self._session_storage.db.getall():
                connector_id = int(connector_id_str)
                chats = self._session_storage.get_extra(connector_id)

                for chat_id in chats:
                    chat = chats[chat_id]

                    last_message_id = chat.get("last_message")

                    if last_message_id:
                        print(f"Last message id in chat {chat_id} was {last_message_id}. Receiving missed messages now...")
                        await self.get_messages(client, connector_id, int(chat_id), f"moca/via/telegram/{connector_id}/messages", min_id=int(last_message_id))


    async def configure(self, client, flow_id, message):
        self.logger.debug("Configure telegram service (triggered by mqtt)")
        flow: ConfigFlow = self._configurator.get_flow(flow_id)

        data = json.loads(message.payload.decode())

        step = await flow.current_step(user_input=data)
        self.logger.debug("Configurator step: %s", flow.current_step.__name__)

        await client.publish(f"{message.topic}/response", json.dumps(step))

        if step.get("step") == "finished":

            # Send all chats now to moca
            dialogs = await self.get_chats(client, flow_id)

            # Send last 100 messages of the newest 10 chats

            for dialog in dialogs[:10]:
                await self.get_messages(client, flow_id, dialog.id, f"moca/via/telegram/{flow_id}/messages")


    async def get_chats(self, client, connector_id):

        self.logger.info("Get chats for connector %s (triggered by mqtt)", connector_id)

        tg: TelegramClient = await self._session_storage.get_session(connector_id)

        if not await tg.is_user_authorized():
            self.logger.warning("User not authorized")
            return

        me_id = (await tg.get_me()).id

        chats = []
        dialogs = await tg.get_dialogs()

        for dialog in dialogs:

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
        return dialogs

    async def convert_tg_message_to_message(self, tg_message: Message, connector_id):

        print(tg_message)

        message = {}
        chat_id = self.get_id(tg_message.peer_id)

        if tg_message.photo:
            #path = await tg_message.download_media(f"../moca-server/storage/{str(uuid.uuid4())}")
            #print('Image saved to', path)  # printed after download is done

            message = {
                "type": "image",
                "url": f"/chats/{chat_id}/messages/{tg_message.id}/media",
                "content": tg_message.text,
            }

        elif tg_message.audio:
            #path = await tg_message.download_media(f"../moca-server/storage/{str(uuid.uuid4())}")
            #print('audio saved to', path)  # printed after download is done

            message = {
                "type": "audio",
                "url": f"/chats/{chat_id}/messages/{tg_message.id}/media",
                "content": tg_message.text,
            }

        elif tg_message.voice:
            #path = await tg_message.download_media(f"../moca-server/storage/{str(uuid.uuid4())}")
            #print('voice saved to', path)  # printed after download is done

            message = {
                "type": "voice",
                "url": f"/chats/{chat_id}/messages/{tg_message.id}/media",
                "content": tg_message.text,
            }

        elif tg_message.video or tg_message.video_note:
            #path = await tg_message.download_media(f"../moca-server/storage/{str(uuid.uuid4())}")
            #print('video saved to', path)  # printed after download is done

            message = {
                "type": "video",
                "url": f"/chats/{chat_id}/messages/{tg_message.id}/media",
                "content": tg_message.text,
            }

        elif tg_message.gif:
            #path = await tg_message.download_media(f"../moca-server/storage/{str(uuid.uuid4())}")
            #print('gif saved to', path)  # printed after download is done

            message = {
                "type": "gif",
                "url": f"/chats/{chat_id}/messages/{tg_message.id}/media",
                "content": tg_message.text,
            }

        elif tg_message.document:
            #path = await tg_message.download_media(f"../moca-server/storage/{str(uuid.uuid4())}")
            #print('Document saved to', path)  # printed after download is done

            message = {
                "type": "document",
                "url": f"/chats/{chat_id}/messages/{tg_message.id}/media",
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

            self._session_storage.update_extra(connector_id, {
                str(self.get_id(event.message.peer_id)): {
                    "last_message": event.message.id
                } 
            })

            await client.publish(
                f"moca/via/telegram/{connector_id}/messages",
                json.dumps(
                    [await self.convert_tg_message_to_message(event.message, connector_id)]
                ),
            )

    async def get_messages(self, client, connector_id: str, chat_id: int, response_topic: str, min_id=None, max_id=None, limit=25):
        """Get a single chat for a user by chat_id."""

        self.logger.info("Get chat %s for user %s (triggered by mqtt)", chat_id, connector_id)

        tg: TelegramClient = await self._session_storage.get_session(connector_id)

        if not await tg.is_user_authorized():
            self.logger.warning("User not authorized")
            return

        chat: Chat = await tg.get_entity(chat_id)

        if min_id:
            messages = await tg.get_messages(chat, limit, min_id=min_id)
        else:
            messages = await tg.get_messages(chat, limit)


        if len(messages) > 0:
            self._session_storage.update_extra(connector_id, {
                str(chat.id): {
                    "last_message": messages[-1].id
                }
            })

        await client.publish(
            response_topic,
            json.dumps(
                [await self.convert_tg_message_to_message(tg_message, connector_id) for tg_message in messages]
            ),
        )

    async def get_media(self, client, connector_id: int, uri: str, response_topic: str):
        """Get a media file by message id."""

        parts = uri.split(":")
        chat_id = int(parts[0])
        message_id = int(parts[1])

        tg: TelegramClient = await self._session_storage.get_session(connector_id)

        if not await tg.is_user_authorized():
            self.logger.warning("User not authorized")
            return

        chat: Chat = await tg.get_entity(chat_id)

        message: Message = None
        async for msg in tg.iter_messages(chat, ids=message_id):
            message = msg

        # path = await message.download_media(f"storage/{str(uuid.uuid4())}")
        # print('File saved to', path)  # printed after download is done

        async for chunk in tg.iter_download(message.media, chunk_size=1048576):
            await client.publish(
                response_topic,
                json.dumps(
                    {
                        "data": base64.b64encode(chunk).decode()
                    }
                ),
            )

        await client.publish(
                response_topic,
                json.dumps(
                    {
                        "data": None,
                        "filename": f"telegram_{connector_id}_{chat_id}_{message_id}{message.file.ext}",
                        "mime": message.file.mime_type
                    }
                ),
            )

    async def get_contact(self, client, connector_id: str, contact_id: int, response_topic: str):
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
            response_topic,
            json.dumps(
                contact
            ),
        )


    async def delete(self, client, connector_id: str, response_topic: str):
        """Delete a connector."""

        self.logger.info("Delete connector %s (triggered by mqtt)", connector_id)

        tg: TelegramClient = await self._session_storage.get_session(connector_id)

        if tg:
            await tg.disconnect()
            await self._session_storage.delete_session(connector_id)

        await client.publish(
            response_topic,
            json.dumps(
                {"success": True}
            ),
        )

    async def send_message(self, client, connector_id: str, message: Dict, response_topic: str):
        """Send a message."""

        self.logger.info("Send message via %s (triggered by mqtt)", connector_id)

        print(message)

        tg: TelegramClient = await self._session_storage.get_session(connector_id)

        if tg:

            if not await tg.is_user_authorized():
                self.logger.warning("User not authorized")
                return

            content = message.get("message")
            chat_id = int(message.get("chat_id"))

            if content and chat_id:
                content_type = content.get("type")
                content_content = content.get("content")

                if content_type == "text" and content:
                    sent = await tg.send_message(chat_id, content_content)

                    await client.publish(
                        response_topic,
                        json.dumps(
                            await self.convert_tg_message_to_message(sent, connector_id)
                        ),
                    )

    @staticmethod
    def get_id(peer):
        if type(peer) is PeerUser:
            return peer.user_id
        elif type(peer) is PeerChat:
            return peer.chat_id
        elif type(peer) is PeerChannel:
            return peer.channel_id

        # Otherwise it's an anonymous message which should return None
        return None
