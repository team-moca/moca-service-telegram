import logging
import os
import time
from uuid import UUID, uuid4

import anyio
import grpc
import messages_pb2
import purerpc
import service_connector_grpc as service_grpc
import service_connector_pb2 as service
from dotenv import load_dotenv
from google.protobuf.timestamp_pb2 import Timestamp

load_dotenv(verbose=True)


async def main():
    async with purerpc.insecure_channel("localhost", 50060) as channel:
        stub = service_grpc.ServiceConnectorStub(channel)

        user = os.environ["TEST_USER_1"]

        async def login(username=None, password=None, two_factor_code=None, tries=0):
            print("try to log in")
            login_response = await stub.Login(
                service.LoginRequest(
                    username=username,
                    password=password,
                    two_factor_code=two_factor_code,
                )
            )

            if tries > 2:
                print("Aborting because of 3 consecutive failed login attempts.")
                return False

            if login_response.status == service.LoginStatus.LOGIN_OK:
                print("login was successful!")
                return True
            elif login_response.status == service.LoginStatus.LOGIN_NEEDS_SECOND_FACTOR:
                print("LOGIN NEEDS A SECOND FACTOR!")
                twofa = input("2FA code: ")

                return await login(
                    username=username,
                    password=password,
                    two_factor_code=twofa,
                    tries=tries + 1,
                )

            elif login_response.status == service.LoginStatus.LOGIN_WRONG_2FA_CODE:
                print("the code you sent was not correct")
                twofa = input("2FA code: ")

                return await login(
                    username=username,
                    password=password,
                    two_factor_code=twofa,
                    tries=tries + 1,
                )

            return False

        if not await login(username=user):
            # login, and if it fails, abort
            print("login failed.")
            return False

        timestamp = Timestamp()
        timestamp.GetCurrentTime()

        message_meta = messages_pb2.MessageMeta(
            message_id=uuid4().bytes,
            service_id=UUID("54b4ae1c-1c6f-4f7e-b2b9-efd7bf5e894b").bytes,
            from_user_id=str(UUID("8c43ba0c-92b3-11ea-bb37-0242ac130002")),
            to_user_id=str(UUID("78f3647d-1e12-4bca-8ce5-a6e5f2da0508")),
            timestamp=timestamp,
        )

        response = await stub.SendMessage(
            messages_pb2.Message(
                meta=message_meta,
                content=messages_pb2.MessageContent(
                    text_message=messages_pb2.TextMessageContent(
                        content=f"Diese Nachricht kommt von {user}"
                    )
                ),
            )
        )
        print(response.status)

        print("-------------")


if __name__ == "__main__":
    anyio.run(main, backend="asyncio")
