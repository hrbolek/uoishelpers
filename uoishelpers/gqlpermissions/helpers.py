
import inspect
import typing

T = typing.TypeVar("T")

Resolvable = typing.Union[
    T,
    typing.Awaitable[T],
    typing.Callable[[], T],
    typing.Callable[[], typing.Awaitable[T]],
]

async def resolve_async_parameter(value: Resolvable[T]) -> T:
    """
    Resolve a value that may be provided directly, as a callable, or as an awaitable.

    This helper normalizes different input forms into a final resolved value.
    It supports the following input types:

    - Direct value of type `T`
    - Awaitable resolving to `T`
    - Callable returning `T`
    - Callable returning an awaitable resolving to `T`

    The resolution process is performed in two steps:

    1. If `value` is callable, it is invoked with no arguments.
    2. If the resulting value is awaitable, it is awaited.

    The final resolved value is then returned.

    Parameters
    ----------
    value:
        A value or factory that produces a value.

        Supported forms:
        - `T`
        - `Awaitable[T]`
        - `Callable[[], T]`
        - `Callable[[], Awaitable[T]]`

    Returns
    -------
    T
        The resolved value.

    Notes
    -----
    - Callables must not require any arguments.
    - Only a single level of resolution is performed:
      if a callable returns another callable, it will not be invoked again.
    - Similarly, nested awaitables are not recursively awaited.
    - No runtime type validation is performed on the returned value.

    Examples
    --------
    Direct value:
    ```python
    result = await resolve_async_parameter(["a", "b"])
    ```

    Callable:
    ```python
    result = await resolve_async_parameter(lambda: ["a", "b"])
    ```

    Async callable:
    ```python
    async def get_roles():
        return ["admin"]

    result = await resolve_async_parameter(get_roles)
    ```

    Awaitable:
    ```python
    async def get_roles():
        return ["admin"]

    result = await resolve_async_parameter(get_roles())
    ```

    Typical use case:
    ----------------
    This function is useful in APIs that accept flexible configuration
    inputs, allowing users to provide either static values or lazily
    computed (possibly asynchronous) values.
    """
    
    if callable(value):
        value = value()
    if inspect.isawaitable(value):
        value = await value
    return value