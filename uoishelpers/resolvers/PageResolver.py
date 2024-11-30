import typing
import strawberry

sentinel = "893b4f74-c4b7-4b35-b638-6592b5ff48ea"

class PageResolver:
    """
    PageResolver[UserGQLModel](whereType=UserFilterGQLModel)
    """    
    @classmethod
    def __class_getitem__(cls, item):
        listType = item
        def result(*, whereType):
            async def resolver(self, info: strawberry.Info, skip: typing.Optional[int]=0, limit: typing.Optional[int]=10, orderby: typing.Optional[str]=None, where: typing.Optional[whereType]=None) -> typing.List[listType]:
                loader = listType.getLoader(info=info)
                where = None if where is None else strawberry.asdict(where)
                results = await loader.page(skip=skip, limit=limit, orderby=orderby, where=where)
                return (listType.from_dataclass(result) for result in results)        
            return resolver       
        return result