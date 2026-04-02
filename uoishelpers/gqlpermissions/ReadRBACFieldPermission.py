import typing
import inspect
import asyncio
import strawberry
from ..resolvers import getUserFromInfo

from functools import cached_property
from strawberry.permission import PermissionExtension
from strawberry.extensions import FieldExtension
class ReadRBACFieldPermission(PermissionExtension):
    """
    Strawberry field permission extension for read operations with RBAC checks.

    This extension is intended for GraphQL field resolvers that return data
    belonging to an RBAC object. Permission is granted when the current user
    has at least one of the required roles on the RBAC object associated with
    the resolved source entity.

    The RBAC object is resolved in two steps:

    1. The primary key value is read from the resolver source object using
       `pk_field_name`.
    2. The source row is loaded through `loader_getter(info)`, and the
       `rbacobject_id` is extracted from the loaded row.

    The user's roles for the given RBAC object are then loaded from
    `info.context["userRolesForRBACQuery_loader"]`.

    The extension also supports composition of nested permissions using
    `any` or `all`.

    Parameters
    ----------
    roles:
        List of RBAC role names that grant access to the field.
        Example: ["administrator", "editor"].

    pk_field_name:
        Name of the attribute on `source` that contains the primary key
        used to load the backing row.

    loader_getter:
        Callable accepting `info` and returning a dataloader able to load
        the row for the given primary key.

    any:
        Optional iterable of permission objects. Access is granted if at least
        one of them grants permission.

    all:
        Optional iterable of permission objects. Access is granted only if all
        of them grant permission.

    Notes
    -----
    - `roles`, `pk_field_name`, and `loader_getter` cannot be combined with
      `any` or `all`.
    - `any` and `all` are mutually exclusive.
    - The extension is intended for read/query field access, not mutations.
    - The backing row loaded by `loader_getter` must contain `rbacobject_id`.

    Required context
    ----------------
    The GraphQL context must provide:

    - `userRolesForRBACQuery_loader`:
      dataloader returning user roles for an RBAC object
    - `getUserFromInfo(info)` must return the current user object with `id`

    Expected row shape
    ------------------
    The row loaded by `loader_getter(info).load(pk)` is expected to contain:

    {
        "id": "...",
        "rbacobject_id": "..."
    }

    Example
    -------
    ```python
    @strawberry.type
    class UserGQLModel:
        id: strawberry.ID
        person_id: strawberry.ID

        @strawberry.field(
            extensions=[
                ReadRBACFieldPermission(
                    roles=["administrator", "editor"],
                    pk_field_name="person_id",
                    loader_getter=lambda info: info.context["person_by_id_loader"],
                )
            ]
        )
        async def address(self, info) -> str:
            ...
    ```

    Example with composed permissions
    ---------------------------------
    ```python
    ReadRBACFieldPermission(
        any=[
            ReadRBACFieldPermission(
                roles=["administrator"],
                pk_field_name="person_id",
                loader_getter=lambda info: info.context["person_by_id_loader"],
            ),
            ReadRBACFieldPermission(...)
        ]
    )
    ```

    Permission algorithm
    --------------------
    1. If `any` is defined, evaluate all nested permissions and allow access
       if any of them returns True.
    2. If `all` is defined, evaluate all nested permissions and allow access
       only if all of them return True.
    3. Otherwise:
       - read `pk_value = getattr(source, pk_field_name)`
       - load row using `loader_getter(info)`
       - extract `rbacobject_id`
       - load current user's roles for the RBAC object
       - return True if any of the user's roles matches one of `roles`

    Failure behavior
    ----------------
    This extension assumes the required data is present and uses assertions
    for internal consistency checks. Missing loaders, missing rows, or missing
    `rbacobject_id` are treated as programming/configuration errors.

    Recommended usage
    -----------------
    Use this extension for query/read fields whose visibility depends on RBAC
    membership derived from a related entity.
    """

    def __init__(
        self, *, 
        roles: typing.List[str]=None,
        pk_field_name: str = None,
        loader_getter: typing.Callable[[strawberry.types.Info], typing.Any] = None,
        any: typing.Any = None,
        all: typing.Any = None
    ):
        self.roles = roles
        self.pk_field_name = pk_field_name
        self.loader_getter = loader_getter
    
        if any is not None and all is not None:
            raise ValueError("Cannot specify both 'any' and 'all' parameters")
    
        if any is not None or all is not None:
            assert roles is None, "Cannot specify 'roles' parameter when using 'any' or 'all'"
            assert loader_getter is None, "loader_getter cannot be provided when using 'any' or 'all'"
            assert pk_field_name is None, "pk_field_name cannot be provided when using 'any' or 'all'"

        self.any = tuple(any) if any is not None else None
        self.all = tuple(all) if all is not None else None

        self.permissions = []
        self.fail_silently = True
        self.return_empty_list = False
        self.use_directives = False

    async def has_permission(
        self, 
        source, 
        info: strawberry.types.Info, 
        **kwargs
    ) -> bool:
        if self.any is not None:
            futures = [perm.has_permission(source, info, **kwargs) for perm in self.any]
            results = await asyncio.gather(*futures)
            return True if any(results) else False
            
        if self.all is not None:
            futures = [perm.has_permission(source, info, **kwargs) for perm in self.all]
            results = await asyncio.gather(*futures)
            return True if all(results) else False
            
        loader = self.loader_getter(info) if self.loader_getter else None
        assert loader is not None, "Loader must be provided to ReadRBACFieldPermission"
        pk_value = getattr(source, self.pk_field_name, None)
        assert pk_value is not None, f"{type(source).__name__}[{getattr(source, 'id', 'unknown')}].{self.pk_field_name}==None, cannot perform RBAC check without this value, access denied"
        dataRow = await loader.load(pk_value) if loader and pk_value else None
        assert dataRow is not None, f"Data row for RBAC check not found for pk {pk_value} with loader {loader}"
        rbacobject_id = dataRow.get("rbacobject_id") if dataRow else None
        assert rbacobject_id is not None, f"rbacobject_id not found in data row for pk {pk_value}"
        user = getUserFromInfo(info=info)
        role_loader = info.context.get("userRolesForRBACQuery_loader", None)
        assert role_loader is not None, "userRolesForRBACQuery_loader must be provided in context"
        params = {
            "id": rbacobject_id,
            "user_id": str(user["id"])
        }

        gql_response = await role_loader.load(params)
        assert gql_response is not None, f"query for user roles was not responded properly {gql_response}"
        assert "result" in gql_response, f"query for user roles was not responded properly {gql_response}"
        user_roles = gql_response["result"]
        print(f"User {user} roles for RBAC check: \n{user_roles}", flush=True)
        matched_roles = [role for role in user_roles if role["roletype"]["name"] in self.roles]

        return bool(matched_roles)

    async def resolve_async(
        self, 
        next_: typing.Callable[..., typing.Awaitable[typing.Any]], 
        source: typing.Any, 
        info: strawberry.types.Info, 
        **kwargs: typing.Any
    ) -> typing.Any:  # pragma: no cover
        print(f"Checking permission on source {source}", flush=True)
        judgement = await self.has_permission(source, info, **kwargs)
        if judgement:
            next = next_(source, info, **kwargs)
            if inspect.isasyncgen(next):
                return next
            return await next
            
        return [] if self.return_empty_list else None
        
    resolve = FieldExtension.resolve
    @cached_property
    def supports_sync(self) -> bool:
        return False
    # (
    #     self,
    #     next_: typing.Callable[..., typing.Any],
    #     source: typing.Any,
    #     info: strawberry.types.Info,
    #     **kwargs: dict[str, typing.Any],
    # ) -> typing.Any:
    #     assert False, "Synchronous resolve is not supported for ReadRBACFieldPermission. Use Async resolve or ensure Strawberry is configured to use async resolvers."
        
