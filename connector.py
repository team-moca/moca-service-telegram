import asyncio
import json
import os
from contextlib import AsyncExitStack, asynccontextmanager
from random import randrange
from asyncio_mqtt import Client, MqttError
from dotenv import load_dotenv
from telethon import TelegramClient, events, sync
from pathlib import Path
from telethon.errors.rpcerrorlist import PhoneCodeInvalidError
from telethon.tl.types import User
from telethon.tl.types.auth import SentCode

load_dotenv(verbose=True)

api_id = os.environ["TELEGRAM_API_ID"]
api_hash = os.environ["TELEGRAM_API_HASH"]

from core.configurator import Configurator


class TgSessionStorage:
    def __init__(self):
        self.sessions = {}

    async def get_session(self, username):

        print("searching session for {}...".format(username))

        # hashed_username = hashlib.sha224(username.encode()).hexdigest()
        hashed_username = username.replace("+", "00")

        session = self.sessions.get(hashed_username)

        if not session:
            session = TelegramClient(f"sessions/{hashed_username}", api_id, api_hash)
            self.sessions[hashed_username] = session

            @session.on(events.NewMessage)
            async def handle_message(event):
                print(event.raw_text)

                await mqtt.publish("moca/messages", json.dumps({
                    "meta": {
                        "service": "TELEGRAM",
                        "user_id": (await session.get_me()).id
                    },
                    "message": event.raw_text
                }))

            await session.start()

            print("no session found. creating new session...")

        return session

session_storage = TgSessionStorage()

configurator = Configurator(session_storage)

mqtt = None

async def advanced_example():

    async with AsyncExitStack() as stack:

        tasks = set()
        stack.push_async_callback(cancel_tasks, tasks)

        client = Client("localhost", client_id="TG000")
        await stack.enter_async_context(client)

        manager = client.filtered_messages("telegram/configure/+")
        messages = await stack.enter_async_context(manager)
        task = asyncio.create_task(configure(client, messages, "telegram/configure/+"))
        tasks.add(task)

        # messages = await stack.enter_async_context(client.unfiltered_messages())
        # task = asyncio.create_task(handle(client, messages, "[unfiltered] {}"))
        # tasks.add(task)

        global mqtt
        mqtt = client

        await client.subscribe("telegram/#")
        await asyncio.gather(*tasks)


async def configure(client, messages, topic_filter):
    async for message in messages:
        print(f"[{message.topic} via {topic_filter}] {message.payload.decode()}")
        flow_id = message.topic.split("/")[2]
        flow = configurator.get_flow(flow_id)

        data = json.loads(message.payload.decode())

        step = await flow.current_step(user_input=data)
        print(f"Current step: {flow.current_step.__name__}")

        await client.publish(f"{message.topic}/response", json.dumps(step))


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
            print(f'Error "{error}". Reconnecting in {reconnect_interval} seconds.')
        finally:
            await asyncio.sleep(reconnect_interval)


asyncio.run(main())
