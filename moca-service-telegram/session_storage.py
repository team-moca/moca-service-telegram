import json
import logging
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

    async def get_session(self, username):

        self.logger.debug("Get session for user %s", username)

        # hashed_username = hashlib.sha224(username.encode()).hexdigest()
        hashed_username = username.replace("+", "00")

        session = self.sessions.get(hashed_username)

        if not session:
            session = TelegramClient(
                f"sessions/{hashed_username}", self.api_id, self.api_hash
            )
            self.sessions[hashed_username] = session

            @session.on(events.NewMessage)
            async def handle_message(event):
                self.logger.trace(event.raw_text)

                await mqtt.publish(
                    "moca/messages",
                    json.dumps(
                        {
                            "meta": {
                                "service": "TELEGRAM",
                                "message_id": event.message.id,
                                "foward_from_id": event.forward.from_id
                                if event.forward
                                else None,
                                "from_user_id": self.get_id(event.message.from_id),
                                "to_chat_id": event.chat_id,
                                "x_to_peer_id": self.get_id(event.message.to_id),
                            },
                            "message": event.raw_text,
                        }
                    ),
                )

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
