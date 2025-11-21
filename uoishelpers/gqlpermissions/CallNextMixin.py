import typing
from typing import Any, Awaitable, Callable
from inspect import isawaitable
import strawberry

class CallNextMixin:
    """
    Mixin, který zjednodušuje volání dalšího kroku v řetězci field extensions.

    Metoda `call_next_resolve(...)` udělá toto:
    - Pokusí se na `super()` najít metodu `resolve_async`.
      - Pokud existuje, zavolá ji (může to být další extension v MRO),
        výsledek případně `await`ne.
      - Pokud neexistuje, zavolá přímo `next_(...)`, což je „další“
        resolver/extension v řetězci, který Strawberry předává.

    Díky tomuto mixinu může každá extension jednoduše udělat:

        return await self.call_next_resolve(next_, source, info, *args, **kwargs)

    místo toho, aby řešila, jestli má volat `super().resolve_async(...)`
    nebo přímo `next_(...)`. Umožňuje to čisté skládání více mixinů/extension
    přes MRO (Method Resolution Order).
    """
        
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
