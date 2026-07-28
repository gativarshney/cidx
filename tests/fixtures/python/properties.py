class Config:
    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, v: int) -> None:
        self._value = v

    @staticmethod
    def default() -> "Config":
        return Config()

    @classmethod
    def parse(cls, raw: str) -> "Config":
        return cls()
