import json
import logging
import os
from typing import Dict, Any

from telethon import TelegramClient, events
from telethon.tl.types import PeerUser, PeerChat, PeerChannel


class SessionStorage:
    def __init__(self, options: Dict[str, Any]):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.sessions = {}
        self.api_id = options.pop("api_id")
        self.api_hash = options.pop("api_hash")

        self.logger.info("Setup session storage")

        self.callbacks = []


    async def delete_session(self, connector_id):
        self.sessions.pop(connector_id, None)
        os.remove(f"sessions/{connector_id}.session")

    async def get_session(self, connector_id: int):

        self.logger.debug("Get session for user %s", connector_id)

        session = self.sessions.get(connector_id)

        if not session:
            session = TelegramClient(
                f"sessions/{connector_id}", self.api_id, self.api_hash
            )
            self.sessions[connector_id] = session

            @session.on(events.NewMessage)
            async def handle_message(event):
                self.logger.debug(event.raw_text)

                for callback in self.callbacks:
                    await callback(connector_id, event)

            self.logger.debug("No session found. Created new session...")

        return session

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
