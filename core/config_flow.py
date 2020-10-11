from telethon import TelegramClient
from telethon.tl.types import User
from telethon.tl.types.account import Password
from telethon.tl.types.auth import SentCode


class ConfigFlow:
    def __init__(self, session_storage):
        super().__init__()
        self.session_storage = session_storage
        self.current_step = self.step_user

        self.phone = None
        self.code = None
        self.password = None

    async def step_user(self, user_input=None):
        """First step in the setup of a new Telegram service connection.
        It only requires the phone number."""
        self.current_step = self.step_user

        # TODO validate schema
        if user_input and user_input.get("phone"):
            self.phone = user_input.get("phone")
            return await self._login()

        return {"phone": "string"}

    async def step_verification_code(self, user_input=None):
        """The second step is to enter the verification code (sent by Telegram via SMS or phone call)."""
        self.current_step = self.step_verification_code

        if user_input and user_input.get("verification_code"):
            self.code = user_input.get("verification_code")
            return await self._login()

        return {"verification_code": {"type": "string", "len": 6}}

    async def step_password(self, user_input=None):
        """Optional third step, if the user activated 2FA with password."""
        self.current_step = self.step_password

        if user_input and user_input.get("password"):
            self.password = user_input.get("password")
            return await self._login()

        return {"password": "string"}

    async def step_finished(self, user_input=None):
        self.current_step = self.step_finished
        return {"finished": True}

    async def _login(self):
        tg: TelegramClient = self.session_storage.get_session(self.phone)

        if not tg.is_connected():
            print("Connecting to Telegram...")
            await tg.connect()

        if await tg.is_user_authorized():
            print("User already authorized.")
            return await self.step_finished()

        try:
            si = await tg.sign_in(self.phone, code=self.code, password=self.password)

            if type(si) is SentCode:
                print("A 2FA code has been sent. Please re-sign-in with this code.")
                return await self.step_verification_code()

            elif type(si) is User:
                print("login successful.")
                return await self.step_finished()

            elif type(si) is Password:
                return await self.step_password()

            else:
                print("unknown si")
        except Exception as e:
            print(f"unknown error: " + e)
