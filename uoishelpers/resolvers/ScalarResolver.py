import typing
import strawberry

sentinel = "893b4f74-c4b7-4b35-b638-6592b5ff48ea"

T = typing.TypeVar("GQLModel")
class ScalarResolver(typing.Generic[T]):
    """
    ScalarResolver[UserGQLModel](fkey_field_name="user_id")
    """
    @classmethod
    def __class_getitem__(cls, item):
        scalarType = item
        def result(*, fkey_field_name):
            async def resolver(self, info: strawberry.Info) -> typing.Optional[scalarType]:
                value = getattr(self, fkey_field_name, sentinel)
                assert (value != sentinel), f"missing value {scalarType}.{fkey_field_name}"
                result = await scalarType.resolve_reference(info=info, id=value)
                return result
            return resolver       
        return result
