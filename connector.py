import service_connector_grpc as service_grpc
import service_connector_pb2 as service
import grpc
from concurrent import futures
from google.protobuf.timestamp_pb2 import Timestamp
import logging
from uuid import UUID, uuid4
import messages_pb2
from telethon import TelegramClient, events, sync
from dotenv import load_dotenv
import os
from purerpc import Server
from telethon.tl.types.auth import SentCode
from telethon.tl.types import User
from telethon.errors.rpcerrorlist import PhoneCodeInvalidError
import hashlib


load_dotenv(verbose=True)

api_id = os.environ["TELEGRAM_API_ID"]
api_hash = os.environ["TELEGRAM_API_HASH"]


class TgSessionStorage:
    def __init__(self):
        self.sessions = {}

    def get_session(self, username):

        print("searching session for {}...".format(username))

        #hashed_username = hashlib.sha224(username.encode()).hexdigest()
        hashed_username = username.replace("+", "00")

        session = self.sessions.get(hashed_username)

        if not session:
            session = TelegramClient(f'sessions/{hashed_username}', api_id, api_hash)
            self.sessions[hashed_username] = session
            print("no session found. creating new session...")

        return session

class ServiceConnector(service_grpc.ServiceConnectorServicer):

    def __init__(self):
        print("init service connector")
        self.session_storage = TgSessionStorage()

    async def Login(self, message):
        print("logging in...")

        phone = message.username
        code = message.two_factor_code

        tg = self.session_storage.get_session(phone)

        if code == "":
            code = None    

        if not tg.is_connected():
            print("connecting to tg...")
            await tg.connect()

        if not await tg.is_user_authorized():
            print("user is not yet authorized")

            try:
                si = await tg.sign_in(phone, code=code)
                print(si)

                if type(si) is SentCode:
                    print("A 2FA code has been sent. Please re-sign-in with this code.")
                    return service.LoginResponse(status=service.LoginStatus.LOGIN_NEEDS_SECOND_FACTOR)
                elif type(si) is User:
                    print("login successful.")
                    return service.LoginResponse(status=service.LoginStatus.LOGIN_OK)

                else:
                    print("unknown si")
                    return service.LoginResponse(status=service.LoginStatus.LOGIN_ERROR)

            except Exception as e:
                print("Got exception:")
                print(type(e), e)

                if type(e) is PhoneCodeInvalidError:
                    return service.LoginResponse(status=service.LoginStatus.LOGIN_WRONG_2FA_CODE)
                
                return service.LoginResponse(status=service.LoginStatus.LOGIN_ERROR)

        else:
            print("user already authorized")
            return service.LoginResponse(status=service.LoginStatus.LOGIN_OK)

        return service.LoginResponse(status=service.LoginStatus.LOGIN_ERROR)

    async def SendMessage(self, message):

        from_user_id = message.meta.from_user_id
        to_user_id = message.meta.to_user_id

        # TODO: Get this data from database
        id_to_phone = {
            UUID("8c43ba0c-92b3-11ea-bb37-0242ac130002").bytes: os.environ["TEST_USER_1"],
            UUID("78f3647d-1e12-4bca-8ce5-a6e5f2da0508").bytes: os.environ["TEST_USER_2"]
        }

        from_user = id_to_phone.get(from_user_id)
        to_user = id_to_phone.get(to_user_id)

        print(f"{from_user} --> {to_user}")

        tg = self.session_storage.get_session(from_user)

        if(message.content.HasField("text_message")):
            print(f"sending message: {message.content.text_message.content}")
            await tg.send_message(to_user, message.content.text_message.content)
            return messages_pb2.SendMessageResponse(status=messages_pb2.SendMessageStatus.OK)   

        return messages_pb2.SendMessageResponse(status=messages_pb2.SendMessageStatus.MESSAGE_CONTENT_NOT_IMPLEMENTED_FOR_SERVICE)


server = Server(50060)
server.add_service(ServiceConnector().service)
server.serve(backend="asyncio")