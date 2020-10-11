import asyncio
import json
from contextlib import AsyncExitStack, asynccontextmanager
from random import randrange
from asyncio_mqtt import Client, MqttError

from core.configurator import Configurator

configurator = Configurator()


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
    while True:
        try:
            await advanced_example()
        except MqttError as error:
            print(f'Error "{error}". Reconnecting in {reconnect_interval} seconds.')
        finally:
            await asyncio.sleep(reconnect_interval)


asyncio.run(main())
