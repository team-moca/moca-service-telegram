import logging
from .session_storage import SessionStorage

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError
from telethon.tl.types import User
from telethon.tl.types.account import Password
from telethon.tl.types.auth import SentCode
from . import schema


class ConfigFlow:
    def __init__(self, flow_id, session_storage: SessionStorage):
        super().__init__()
        self.flow_id = flow_id
        self.session_storage = session_storage
        self.current_step = self.step_user

        self.phone = None
        self.code = None
        self.password = None
        self.contact = {}

    async def step_user(self, user_input=None):
        """First step in the setup of a new Telegram service connection.
        It only requires the phone number."""
        self.current_step = self.step_user

        # TODO validate schema
        if user_input:
            self.phone = user_input.get("phone")
            return await self._login()

        return {"step": "phone", "schema": schema.schemas.get("phone")}

    async def step_verification_code(self, user_input=None):
        """The second step is to enter the verification code (sent by Telegram via SMS or phone call)."""
        self.current_step = self.step_verification_code

        if user_input and user_input.get("verification_code"):
            self.password = None
            self.code = user_input.get("verification_code")
            return await self._login()

        return {
            "step": "verification_code",
            "schema": schema.schemas.get("verification_code"),
        }

    async def step_password(self, user_input=None):
        """Optional third step, if the user activated 2FA with password."""
        self.current_step = self.step_password

        if user_input and user_input.get("password"):
            self.code = None
            self.password = user_input.get("password")
            return await self._login()

        return {"step": "password", "schema": schema.schemas.get("password")}

    async def step_finished(self, user_input=None):
        self.current_step = self.step_finished
        return {"step": "finished", "data": {"contact": self.contact}}

    async def _login(self):
        tg: TelegramClient = await self.session_storage.get_session(self.flow_id)

        if not tg.is_connected():
            print("Connecting to Telegram...")
            await tg.connect()

        if await tg.is_user_authorized():
            print("User already authorized.")
            me = await tg.get_me()

            self.contact = {
                "id": me.id,
                "name": f"{me.first_name} {me.last_name}",
                "username": me.username,
                "phone": f"+{me.phone}",
            }

            return await self.step_finished()

        try:
            si = await tg.sign_in(self.phone, code=self.code, password=self.password)

            if type(si) is SentCode:
                print("A 2FA code has been sent. Please re-sign-in with this code.")
                return await self.step_verification_code()

            elif type(si) is User:
                print("login successful.")

                me = await tg.get_me()

                self.contact = {
                    "id": me.id,
                    "name": f"{me.first_name} {me.last_name}",
                    "username": me.username,
                    "phone": f"+{me.phone}",
                }

                return await self.step_finished()

            elif type(si) is Password:
                return await self.step_password()

            else:
                print("unknown si")
        except PhoneCodeInvalidError:
            print("Code wrong")
            return await self.step_verification_code()
        except SessionPasswordNeededError as e:
            print("requiring password")
            print(e)
            return await self.step_password()
        except Exception as e:
            print(f"unknown error: " + e)


class Configurator:
    def __init__(self, session_storage: SessionStorage):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)

        self.session_storage = session_storage
        self.active_flows = {}
        self.logger.info("Starting configurator")

    def get_flow(self, flow_id):

        flow = self.active_flows.get(flow_id)

        if not flow:
            self.active_flows[flow_id] = ConfigFlow(flow_id, self.session_storage)

        return self.active_flows.get(flow_id)
