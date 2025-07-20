import typing
import strawberry
from uoishelpers.resolvers import DeleteError

from .UpdatePermissionCheckRoleFieldExtension import UpdatePermissionCheckRoleFieldExtension
import functools
T = typing.TypeVar("T")
class DeletePermissionCheckRoleFieldExtension(UpdatePermissionCheckRoleFieldExtension, typing.Generic[T]):
    GQLModel: typing.Type[T] = None  # Default type, can be overridden by __class_getitem__
    @classmethod
    @functools.cache
    def __class_getitem__(cls, item):
        # When MyGenericClass[int] is accessed, create a new class with type_arg set
        new_cls = type(f"{cls.__name__}[{item if isinstance(item, str) else item.__name__}]", (cls,), {"GQLModel": item})
        return new_cls

    def return_error(self, info: strawberry.types.Info, message: str, code: str, input_data: typing.Any = None):
        error_description = {
            "msg": message,
            "code": code,
            "_input": input_data or {},
            "location": self.get_path_string(info.path) if hasattr(info, "path") and info.path else None
        }
        info.context["errors"].append(error_description)
        return DeleteError[self.GQLModel](**error_description)

