import os
import random

from dotenv import load_dotenv
from telethon import TelegramClient, events, sync

load_dotenv(verbose=True)

# These example values won't work. You must get your own api_id and
# api_hash from https://my.telegram.org, under API Development.
api_id = os.environ["TELEGRAM_API_ID"]
api_hash = os.environ["TELEGRAM_API_HASH"]


def verbuchseln(input):
    words = input.split()

    firstchars = []
    rests = []

    # extract first characters
    for word in words:
        firstchars.append(word[0])
        rests.append(word[1:])

    print(firstchars)
    print(rests)

    sentence = []

    for rest in rests:
        firstcharindex = random.randint(0, len(firstchars) - 1)
        firstchar = firstchars.pop(firstcharindex)
        sentence.append(firstchar + rest)

    return str.lower(str.join(" ", sentence))


with TelegramClient("moca-service-telegram", api_id, api_hash) as client:

    print(client.get_me().stringify())

    client.send_message("", "Hallo!")

    # client.download_profile_photo('me')
    # messages = client.get_messages('+4915170177034')
    # messages[0].download_media()

    @client.on(events.NewMessage())
    async def handler(event):
        await event.respond(verbuchseln(event.message.message))

    client.run_until_disconnected()
