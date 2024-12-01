import typing
import functools
import strawberry

sentinel = "893b4f74-c4b7-4b35-b638-6592b5ff48ea"

T = typing.TypeVar("GQLModel")
class VectorResolver(typing.Generic[T]):
    """
    VectorResolver[UserGQLModel](fkey_field_name="user_id", whereType=UserFilterGQLModel)
    """
    @classmethod
    @functools.cache
    def __class_getitem__(cls, item):
        @functools.cache
        def result(*, fkey_field_name, whereType):
            listType = None
            initialized = False
            def resolveResultType(info: strawberry.types.Info):
                return_type = info.return_type
                if (return_type.__class__.__name__ == "StrawberryOptional"):
                    return_type = return_type.of_type

                if (return_type.__class__.__name__ == "StrawberryList"):
                    return_type = return_type.of_type

                if (isinstance(return_type, strawberry.LazyType)):
                    return_type = return_type.resolve_type()

                nonlocal listType
                listType = return_type
                return return_type    
            
            async def resolver(self, info: strawberry.Info, skip: typing.Optional[int]=0, limit: typing.Optional[int]=10, orderby: typing.Optional[str]=None, where: typing.Optional[whereType]=None) -> typing.List[listType]:
                if not initialized: resolveResultType(info=info)
                # value = getattr(self, fkey_field_name, sentinel)
                # assert (value != sentinel), f"missing value {listType}.{fkey_field_name}"
                extendedfilter = {fkey_field_name: self.id}
                loader = listType.getLoader(info=info)
                where = None if where is None else strawberry.asdict(where)
                results = await loader.page(skip=skip, limit=limit, orderby=orderby, where=where, extendedfilter=extendedfilter)
                return (listType.from_dataclass(result) for result in results)        
            return resolver       
        return result
