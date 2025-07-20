import typing
from typing import Any, Awaitable, Callable
from inspect import isawaitable
import strawberry

class CallNextMixin:
    async def call_next_resolve(
        self,
        next_: Callable[..., Awaitable[Any]],
        source: Any,
        info: strawberry.types.Info,
        *args: Any,
        **kwargs: Any
    ):
        sup = super()
        resolve_async = getattr(sup, "resolve_async", None)
        if resolve_async:
            result = resolve_async(next_, source, info, *args, **kwargs)
            if isawaitable(result):
                return await result
            else:
                return result
        else:
            return await next_(source, info, *args, **kwargs)
