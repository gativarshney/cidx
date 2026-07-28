from typing import TYPE_CHECKING

try:
    import orjson as json_impl
except ImportError:
    import json as json_impl

if TYPE_CHECKING:
    from collections import OrderedDict

DEBUG = False

if DEBUG:
    def log(msg):
        print(msg)
else:
    def log(msg):
        pass
