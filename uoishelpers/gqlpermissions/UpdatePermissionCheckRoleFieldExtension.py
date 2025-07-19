import typing
import strawberry
from strawberry.federation.schema_directive import schema_directive, Location
from strawberry.directive import DirectiveLocation
from strawberry.extensions import FieldExtension
from uoishelpers.dataloaders import getLoadersFromInfo, getUserFromInfo
from uoishelpers.resolvers import InsertError, UpdateError

@schema_directive(
    repeatable=True,
    compose=True,
    description="Označuje, že pole je chráněné a kontroluje oprávnění pomocí PermissionCheckRoleExtension",
    locations=[Location.FIELD_DEFINITION, DirectiveLocation.FIELD],
)
class PermissionCheckRoleDirective:
    roles: list[str]  # parametr, můžeš předat povolené role

import functools
T = typing.TypeVar("T")
class UpdatePermissionCheckRoleFieldExtension(FieldExtension, typing.Generic[T]):
    GQLModel: typing.Type[T] = None  # Default type, can be overridden by __class_getitem__
    @classmethod
    @functools.cache
    def __class_getitem__(cls, item):
        # When MyGenericClass[int] is accessed, create a new class with type_arg set
        new_cls = type(f"{cls.__name__}[{item if isinstance(item, str) else item.__name__}]", (cls,), {"GQLModel": item})
        return new_cls

    def __init__(self, *, roles: typing.Optional[typing.List[str]]):
        self.roles = tuple(roles) # ("garant", "administrátor")

    def apply(self, field):
        # Pokud pole ještě direktivu nemá, přidáme ji automaticky
        has_directive = any(isinstance(d, PermissionCheckRoleDirective) for d in field.directives)

        if not has_directive:
            directive_instance = PermissionCheckRoleDirective(roles=self.roles)
            # Přidáme direktivu do pole
            field.directives.append(directive_instance)

    def get_path_string(self, path) -> str:
        parts = []
        current = path
        while current is not None:
            parts.append(str(current.key))
            current = current.prev
        return ".".join(reversed(parts))
    
    def return_error(self, info: strawberry.types.Info, message: str, code: str, input_data: typing.Any = None):
        error_description = {
            "msg": message,
            "code": code,
            "_input": input_data or {},
            "location": self.get_path_string(info.path) if hasattr(info, "path") and info.path else None
        }
        info.context["errors"].append(error_description)
        return UpdateError[self.GQLModel](**error_description)

    async def resolve_async(self, next_, source, info: strawberry.types.Info, *args, **kwargs):
        input_params = next(iter(kwargs.values()), None)
        if input_params is None:
            return self.return_error(
                info=info,
                message="No input parameters provided",
                code="c4e3cd62-64a9-458d-8d88-e76629be1307",
                input_data=input_params
            )
            
        id = getattr(input_params, "id", None)
        if id is None:
            return self.return_error(
                info=info,
                message="id is required in input parameters",
                code="a849f652-663b-4658-b594-920b7b9355c6",
                input_data=input_params
            )
        
        loader = input_params.getLoader(info=info)
        db_row = await loader.load(input_params.id)
        if db_row is None:
            return self.return_error(
                info=info,
                message="data_row not found",
                code="a8c2c427-681b-4d46-8d9f-4b833f0c0051",
                input_data=input_params
            )
        
        rbacobject_id = getattr(db_row, "rbacobject_id", None)
        # rbacobject_id = "8191cee1-8dba-4a2a-b9af-3f986eb0b51a"
        if rbacobject_id is None:
            return self.return_error(
                info=info,
                message="rbacobject_id is not set in data_row",
                code="00f53a67-3973-4986-b4ee-5939c21da684",
                input_data=input_params
            )

        userCanWithoutState_loader = info.context.get("userCanWithoutState_loader", None)
        assert userCanWithoutState_loader is not None, "userCanWithoutState_loader must be provided in context"
        user = getUserFromInfo(info=info)
        # roles = ("garant", "administrátor")

        params = {
            "id": rbacobject_id,
            "roles": self.roles,
            "user_id": str(user["id"])
        }

        userCanWithoutState = await userCanWithoutState_loader.load(params)
        if userCanWithoutState:
            return await next_(source, info, *args, **kwargs)
        # print(f"userCanWithoutState: {userCanWithoutState}")
        else:
            return self.return_error(
                info=info,
                message=f"You are not allowed to run this mutation with roles {self.roles}",
                code="f7d82b6b-cbbd-4cc7-a181-9273bacc09e1",
                input_data=input_params
            )
                
    