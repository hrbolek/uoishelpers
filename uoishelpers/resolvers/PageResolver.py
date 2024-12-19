import typing
import strawberry

sentinel = "893b4f74-c4b7-4b35-b638-6592b5ff48ea"

T = typing.TypeVar("GQLModel")
class PageResolver(typing.Generic[T]):
    """
    PageResolver[UserGQLModel](whereType=UserFilterGQLModel)
    """    
    @classmethod
    def __class_getitem__(cls, item):
        listType = item
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
            nonlocal initialized
            initialized = True
            return return_type    
            
        def result(*, whereType):
            async def resolver(self, info: strawberry.Info, skip: typing.Optional[int]=0, limit: typing.Optional[int]=10, orderby: typing.Optional[str]=None, where: typing.Optional[whereType]=None) -> typing.List[listType]:
                if not initialized: resolveResultType(info=info)
                loader = listType.getLoader(info=info)
                where = None if where is None else strawberry.asdict(where)
                results = await loader.page(skip=skip, limit=limit, orderby=orderby, where=where)
                return (listType.from_dataclass(result) for result in results)        
            return resolver       
        return result