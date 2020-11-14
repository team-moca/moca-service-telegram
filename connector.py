import asyncio
import json
import os
import sys
import threading
from contextlib import AsyncExitStack, asynccontextmanager
import logging
import logging.handlers
from random import randrange
from asyncio_mqtt import Client, MqttError
from dotenv import load_dotenv
from telethon import TelegramClient, events, sync
from pathlib import Path
from telethon.errors.rpcerrorlist import PhoneCodeInvalidError
from telethon.tl.types import User, PeerUser, PeerChannel, PeerChat
from telethon.tl.types.auth import SentCode

_LOGGER = logging.getLogger(__name__)
logging.basicConfig(stream=sys.stdout, level=logging.INFO)


def setup_logging(log_file, log_no_color=False, verbose=False, log_rotate_days=7):
    # Set up logging
    fmt = "%(asctime)s %(levelname)s (%(threadName)s) [%(name)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    if not log_no_color:
        try:
            # pylint: disable=import-outside-toplevel
            from colorlog import ColoredFormatter

            # basicConfig must be called after importing colorlog in order to
            # ensure that the handlers it sets up wraps the correct streams.
            logging.basicConfig(level=logging.INFO)

            colorformat = f"%(log_color)s{fmt}%(reset)s"
            logging.getLogger().handlers[0].setFormatter(
                ColoredFormatter(
                    colorformat,
                    datefmt=datefmt,
                    reset=True,
                    log_colors={
                        "DEBUG": "cyan",
                        "INFO": "green",
                        "WARNING": "yellow",
                        "ERROR": "red",
                        "CRITICAL": "red",
                    },
                )
            )
        except ImportError:
            pass

        logging.basicConfig(format=fmt, datefmt=datefmt, level=logging.INFO)

        sys.excepthook = lambda *args: logging.getLogger(None).exception(
            "Uncaught exception", exc_info=args  # type: ignore
        )

        if sys.version_info[:2] >= (3, 8):
            threading.excepthook = lambda args: logging.getLogger(None).exception(
                "Uncaught thread exception",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )

        err_log_path = os.path.abspath(log_file)

        err_path_exists = os.path.isfile(err_log_path)
        err_dir = os.path.dirname(err_log_path)

        # Check if we can write to the error log if it exists or that
        # we can create files in the containing directory if not.
        if (err_path_exists and os.access(err_log_path, os.W_OK)) or (
                not err_path_exists and os.access(err_dir, os.W_OK)
        ):

            if log_rotate_days:
                err_handler: logging.FileHandler = (
                    logging.handlers.TimedRotatingFileHandler(
                        err_log_path, when="midnight", backupCount=log_rotate_days
                    )
                )
            else:
                err_handler = logging.FileHandler(err_log_path, mode="w", delay=True)

            err_handler.setLevel(logging.INFO if verbose else logging.WARNING)
            err_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))

            logger = logging.getLogger("")
            logger.addHandler(err_handler)
            logger.setLevel(logging.INFO if verbose else logging.WARNING)

        else:
            _LOGGER.error("Unable to set up error log %s (access denied)", err_log_path)

setup_logging("moca-service-telegram.log", verbose=True)


load_dotenv(verbose=True)

api_id = os.environ["TELEGRAM_API_ID"]
api_hash = os.environ["TELEGRAM_API_HASH"]

from core.configurator import Configurator


class TgSessionStorage:
    def __init__(self):
        self.sessions = {}

    async def get_session(self, username):

        _LOGGER.debug("Get session for user %s", username)

        # hashed_username = hashlib.sha224(username.encode()).hexdigest()
        hashed_username = username.replace("+", "00")

        session = self.sessions.get(hashed_username)

        if not session:
            session = TelegramClient(f"sessions/{hashed_username}", api_id, api_hash)
            self.sessions[hashed_username] = session

            @session.on(events.NewMessage)
            async def handle_message(event):
                _LOGGER.trace(event.raw_text)


                await mqtt.publish("moca/messages", json.dumps({
                    "meta": {
                        "service": "TELEGRAM",
                        "message_id": event.message.id,
                        "foward_from_id": event.forward.from_id if event.forward else None,
                        "from_user_id": get_id(event.message.from_id),
                        "to_chat_id": event.chat_id,
                        "x_to_peer_id": get_id(event.message.to_id)
                    },
                    "message": event.raw_text
                }))

            _LOGGER.debug("No session found. Creating new session...")
            await session.start()

        return session

session_storage = TgSessionStorage()

configurator = Configurator(session_storage)

mqtt = None

def get_id(peer):
    if type(peer) is PeerUser:
        return peer.user_id
    elif type(peer) is PeerChat:
        return peer.chat_id
    elif type(peer) is PeerChannel:
        return peer.channel_id

    # Otherwise it's an anonymous message which should return None
    return None

async def advanced_example():

    async with AsyncExitStack() as stack:

        tasks = set()
        stack.push_async_callback(cancel_tasks, tasks)

        client = Client("localhost", client_id="TG000")
        await stack.enter_async_context(client)

        manager = client.filtered_messages("telegram/configure/+")
        messages = await stack.enter_async_context(manager)

        tasks.add(asyncio.create_task(configure(client, messages, "telegram/configure/+")))

        manager2 = client.filtered_messages("telegram/users/+/get_chats")
        messages2 = await stack.enter_async_context(manager2)

        tasks.add(asyncio.create_task(get_chats(client, messages2, "telegram/users/+/get_chats")))

        # messages = await stack.enter_async_context(client.unfiltered_messages())
        # task = asyncio.create_task(handle(client, messages, "[unfiltered] {}"))
        # tasks.add(task)

        global mqtt
        mqtt = client

        await client.subscribe("telegram/#")
        await asyncio.gather(*tasks)


async def configure(client, messages, topic_filter):
    async for message in messages:
        _LOGGER.debug("Configure telegram service (triggered by mqtt)")
        flow_id = message.topic.split("/")[2]
        flow = configurator.get_flow(flow_id)

        data = json.loads(message.payload.decode())

        step = await flow.current_step(user_input=data)
        _LOGGER.debug("Configurator step: %s", flow.current_step.__name__)

        await client.publish(f"{message.topic}/response", json.dumps(step))


async def get_chats(client, messages, topic_filter):
    async for message in messages:
        phone = message.topic.replace("telegram/users/", "").replace("/get_chats", "")

        _LOGGER.debug("Get chats for user %s (triggered by mqtt)", phone)

        tg: TelegramClient = await session_storage.get_session(phone)

        if not await tg.is_user_authorized():
            _LOGGER.warning("User not authorized")
            break

        chats = []

        for dialog in await tg.get_dialogs():
            chats.append({
                "title": dialog.title,
                "chat_id": dialog.id
            })

        await client.publish(f"{message.topic}/response", json.dumps(chats))


async def cancel_tasks(tasks):
    for task in tasks:
        if task.done():
            continue
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def main():

    reconnect_interval = 3  # [seconds]
    # Initialize all tg sessions
    for session in Path("sessions").rglob("*.session"):
        await session_storage.get_session(session.name[:-8])

    while True:
        try:
            await advanced_example()
        except MqttError as error:
            _LOGGER.error("Error %s. Reconnecting in %s seconds.", error, reconnect_interval)
        finally:
            await asyncio.sleep(reconnect_interval)


asyncio.run(main())
