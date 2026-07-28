class Point:
    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y

    def __repr__(self) -> str:
        return format_point(self)

    async def move(self, dx: float) -> None:
        await animate(self)
