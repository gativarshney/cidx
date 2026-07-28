"""Top-level, nested, and async functions."""


def add(a: int, b: int = 0) -> int:
    """Add two numbers."""
    return a + b


def outer():
    def inner(x):
        return x

    return inner


async def fetch(url: str) -> bytes:
    return await download(url)
