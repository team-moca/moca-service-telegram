class ConfigFlow:
    def __init__(self):
        super().__init__()
        self.current_step = self.step_user

    async def step_user(self, user_input=None):
        """First step in the setup of a new Telegram service connection.
        It only requires the phone number."""
        self.current_step = self.step_user

        if user_input:
            return await self.step_verification_code()

        return {"phone": "string"}

    async def step_verification_code(self, user_input=None):
        """The second step is to enter the verification code (sent by Telegram via SMS or phone call)."""
        self.current_step = self.step_verification_code

        if user_input:
            return await self.step_password()

        return {"verification_code": {"type": "string", "len": 6}}

    async def step_password(self, user_input=None):
        """Optional third step, if the user activated 2FA with password."""
        self.current_step = self.step_password

        if user_input:
            return await self.step_finished()

        return {"password": "string"}

    async def step_finished(self, user_input=None):
        self.current_step = self.step_finished
        return {"finished": True}
