import typing
import inspect
import strawberry

from .TwoStageGenericBaseExtension import TwoStageGenericBaseExtension
from .CallNextMixin import CallNextMixin

READMODE = "957c4c45-7795-4750-9f07-4030e20b87ea"
WRITEMODE = "a1d14583-5918-44f2-b28a-0e720486032e"

class StatefulPermissionAccessControlExtension(TwoStageGenericBaseExtension, CallNextMixin):
    """
    Finální access-control extension, která rozhodne o přístupu na základě:
    - rolí uživatele načtených UserRoleProviderExtension (`user_roles`)
    - požadovaných rolí vrácených `GQLModel.permissions(...)`

    Očekává, že dříve v pipeline už proběhlo:
    - LoadDataExtension -> dodá `db_row`
    - RbacProviderExtension -> dodá `rbacobject_id`
    - UserRoleProviderExtension -> dodá `user_roles`

    `GQLModel.permissions(...)` má vrátit množinu / iterovatelný seznam ID rolí,
    které jsou pro daný objekt, stav a operaci vyžadovány.
    """

    def __init__(
        self,
        *,
        operation_id: typing.Any = None,
        read_mode: bool = False,
        write_mode: bool = False,
    ):
        if read_mode and write_mode:
            raise ValueError("read_mode and write_mode cannot be both True")
        if not read_mode and not write_mode:
            raise ValueError("Either read_mode or write_mode must be True")
    
        self.operation_id = operation_id
        if read_mode:
            self.mode = READMODE
        else:
            self.mode = WRITEMODE
        
        super().__init__()

    @classmethod
    def read(cls, operation_id: typing.Any=None):
        """
        Zkrácený název pro `StatefulPermissionAccessControlExtension(operation_id=..., read_mode=True)`
        """
        return cls(operation_id=operation_id, read_mode=True)
    
    @classmethod
    def write(cls, operation_id: typing.Any=None):
        """
        Zkrácený název pro `StatefulPermissionAccessControlExtension(operation_id=..., write_mode=True)`
        """
        self = cls(operation_id=operation_id, write_mode=True)
        assert self.GQLModel is not None, "GQLModel must be defined for write access control"
        assert self.ErrorType is not None, "ErrorType must be defined for write access control"
        return self
    
    async def resolve_async_read(
        self, 
        next_, 
        info: strawberry.types.Info, 
        source: typing.Any,
        **kwargs
    ):
        from .UserRoleProviderExtension import UserRoleProviderExtension
        if (user_roles := kwargs.get("user_roles", None)) is None:
            rbacobject_id = getattr(source, "rbacobject_id", None) or kwargs.get("rbacobject_id", None)
            if rbacobject_id is None:
                return None
            user_roles = await UserRoleProviderExtension.resolve_user_roles(
                info=info, 
                rbacobject_id=rbacobject_id
            )
        
        cls = self.GQLModel or type(source)

        permissions_fn = getattr(cls, "permissions", None)
        assert permissions_fn is not None, (
            f"{cls.__name__}.permissions(...) must be defined"
        )

        required_role_ids = await permissions_fn(
            info=info, 
            source=source, 
            operation_id=self.operation_id)

        if required_role_ids:
            required_role_ids = {
                f"{r}" for r in required_role_ids
            }

        print(f"cls={cls}")
        print(f"StatefulPermissionAccessControlExtension.resolve_async_read: user_roles=\n{user_roles}\n{required_role_ids}")
        if required_role_ids:
            matched_roles = [
                role for role in user_roles
                if (
                    role.get("roletype") is not None
                    and role["roletype"].get("id") in required_role_ids
                )
            ]

            if matched_roles:
                return await self.call_next_resolve(next_, source, info, **kwargs)

        # print(f"{info.return_type} access denied for user roles {user_roles} (required: {required_role_ids})")
        if type(info.return_type).__name__ == "StrawberryList":
            # Pokud je návratový typ Optional, vracíme None místo chyby
            return []
        return None


    async def resolve_async_write(
        self, 
        next_, 
        info: strawberry.types.Info, 
        source: typing.Any,
        **kwargs
    ):
        user_roles = kwargs.get("user_roles", None)
        cls = self.GQLModel or type(source)

        input_params = next(iter(kwargs.values()), None)
        user_roles = kwargs.get("user_roles", None)
        db_row = kwargs.get("db_row", None)

        assert user_roles is not None, (
            "Bad configuration of field extensions, missing UserRoleProviderExtension"
        )

        permissions_fn = getattr(cls, "permissions", None)
        assert permissions_fn is not None, (
            f"{cls.__name__}.permissions(...) must be defined"
        )

        required_role_ids = await permissions_fn(
            info=info, 
            source=db_row, 
            operation_id=self.operation_id,
            **kwargs)

        if not required_role_ids:
            return self.return_error(
                info=info,
                message="you are not authorized",
                code="1bc8c5ec-da65-42aa-9d7f-e82a80d2aed9",
                input_data=input_params,
            )

        matched_roles = [
            role for role in user_roles
            if (
                role.get("roletype") is not None
                and role["roletype"].get("id") in required_role_ids
            )
        ]

        if matched_roles:
            kwargs["user_roles"] = matched_roles
            # kwargs["required_role_ids"] = required_role_ids
            return await self.call_next_resolve(next_, source, info, **kwargs)

        return self.return_error(
            info=info,
            message="you are not authorized",
            code="66249ce2-4352-4973-b785-f3fca497d2ad",
            input_data=input_params
        )

    async def resolve_async(
        self, 
        next_, 
        source, 
        info: strawberry.types.Info, 
        **kwargs
    ):
        if self.mode == READMODE:
            return await self.resolve_async_read(next_, info, source, **kwargs)
        if self.mode == WRITEMODE:
            return await self.resolve_async_write(next_, info, source, **kwargs)
        assert False, "Invalid mode for StatefulPermissionAccessControlExtension"