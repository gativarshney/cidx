import functools

from flask import app


@functools.cache
def cached():
    return 1


@app.route("/health")
def health():
    return ping()
