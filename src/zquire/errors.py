class ZquireError(Exception):
    def __init__(self, code: str, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict:
        payload = {"code": self.code, "message": self.message}
        if self.hint is not None:
            payload["hint"] = self.hint
        return payload
