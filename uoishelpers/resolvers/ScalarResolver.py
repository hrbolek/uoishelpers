import typing
import strawberry
from strawberry import LazyType 
sentinel = "893b4f74-c4b7-4b35-b638-6592b5ff48ea"

# from typing import Annotated, ForwardRef, get_type_hints
# from strawberry.types.lazy_type import StrawberryLazyReference
# def resolve_type(annotation, globalns=None):
#     if hasattr(annotation, "__metadata__"):  # For Annotated types
#         __args__ = getattr(annotation, "__args__")
#         lazy: StrawberryLazyReference = annotation.__metadata__[0]
#         base_type = lazy.resolve_forward_ref(__args__[0])
#         base_type = base_type.resolve_type()
#         print(f"lazy resolved {base_type}")
#         return base_type

#     elif hasattr(annotation, "__args__"):  # For Annotated types
#         base_type = annotation.__args__
#         print(f"annotation.__args__ {base_type}")
#         if len(base_type) == 2:
#             print(f"resolving len==2")
#             lazy: StrawberryLazyReference = base_type[1]
#             base_type = lazy.resolve_forward_ref(base_type[1])
#             base_type.resolve_type()
#         else:
#             base_type = base_type[0]
#         print(f"base_type {base_type}")
#         if isinstance(base_type, ForwardRef):
#             r = get_type_hints(base_type, globalns)
#             print(f"r {r}")
#             return r
#         else:
#             print(f"is not ForwardRef {base_type}")
#         return base_type
#     else:
#         print(f"has not {annotation}")
#     if isinstance(annotation, ForwardRef):  # For standalone ForwardRef
#         return get_type_hints(annotation, globalns)["temp"]
#     else:
#         print(f"has not {annotation}")
#     return annotation    


T = typing.TypeVar("GQLModel")
class ScalarResolver(typing.Generic[T]):
    """
    ScalarResolver[UserGQLModel](fkey_field_name="user_id")
    """

    @classmethod
    def __class_getitem__(cls, item):
        scalarType = None
        initialized = False
        def resolveResultType(info: strawberry.types.Info):
            return_type = info.return_type
            if (return_type.__class__.__name__ == "StrawberryOptional"):
                return_type = return_type.of_type

            if (return_type.__class__.__name__ == "StrawberryList"):
                return_type = return_type.of_type

            if (isinstance(return_type, strawberry.LazyType)):
                return_type = return_type.resolve_type()

            nonlocal scalarType
            scalarType = return_type
            return return_type

        def result(*, fkey_field_name):
            async def resolver(self, info: strawberry.Info) -> typing.Optional[scalarType]:
                if not initialized: resolveResultType(info=info)
                value = getattr(self, fkey_field_name, sentinel)
                assert (value != sentinel), f"missing value {scalarType}.{fkey_field_name}"
                result = await scalarType.resolve_reference(info=info, id=value)
                return result
            return resolver       
        return result
