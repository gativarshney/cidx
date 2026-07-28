from dataclasses import dataclass


class Base:
    """Base class."""

    LIMIT: int = 10

    def save(self) -> None:
        self.validate()

    def validate(self) -> None:
        pass


@dataclass
class User(Base):
    name: str = "anonymous"

    @property
    def display(self) -> str:
        return self.name.title()
