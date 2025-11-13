import typing
import datetime
import strawberry

from .fromContext import getUserFromInfo

from .IDType import IDType

DeleteType = typing.TypeVar("GQLEntityType")    

@strawberry.type(description="Error object returned as an result of Delete operation")
class DeleteError(typing.Generic[DeleteType]):
    _entity: typing.Optional[DeleteType] = strawberry.field(default=None, description="Entity to be updated")
    msg: str = strawberry.field(default=None, description="reason of fail")
    code: typing.Optional[IDType] = strawberry.field(default=None, description="error code, if available")
    failed: bool = strawberry.field(default=True, description="always True, available when error")
    location: typing.Optional[str] = strawberry.field(default=None, description="location of the error - resolver name")
    _input: strawberry.Private[object]

    @classmethod
    @cache
    def __class_getitem__(cls, item):
        # When MyGenericClass[int] is accessed, create a new class with type_arg set
        new_cls = type(f"{cls.__name__}[{item if isinstance(item, str) else item.__name__}]", (cls,), {"type_arg": item})
        return new_cls
    
    @strawberry.field(description="original data")
    def input(self) -> typing.Optional[strawberry.scalars.JSON]:
        if self._input is None:
            return None
        d = {key: f"{value}" if isinstance(value, (datetime.datetime, IDType)) else value for key, value in strawberry.asdict(self._input).items() if value is not None}
        return d

from functools import cache
class Delete:
    type_arg = None  # Placeholder for the generic type argument
  
    @classmethod
    @cache
    def __class_getitem__(cls, item):
        # When MyGenericClass[int] is accessed, create a new class with type_arg set
        new_cls = type(f"{cls.__name__}[{item.__name__}]", (cls,), {"type_arg": item})
        return new_cls

    @classmethod
    async def DoItSafeWay(cls, info, entity):
        type_arg = cls.type_arg
        try:
            loader = type_arg.getLoader(info=info)
            row = await loader.load(entity.id)
            timestamp = getattr(row, "lastchange", None)
            if timestamp:
                if timestamp != entity.lastchange:
                    # code = "7163dd9c-752c-4d1d-a89e-0bdbc7988a8e"
                    location = cls.get_path_string(info.path) if hasattr(info, "path") and info.path else None

                    return DeleteError[type_arg](
                        _entity=_entity, 
                        msg=f"Someone changed entity", 
                        location=location,
                        _input=entity
                    )
            await loader.delete(entity.id)
            return None
        except Exception as e:
            _entity = await type_arg.resolve_reference(info=info, id=entity.id)
            # code = "7163dd9c-752c-4d1d-a89e-0bdbc7988a8e"
            location = cls.get_path_string(info.path) if hasattr(info, "path") and info.path else None
            return DeleteError[type_arg](
                _entity=_entity, 
                location=location,
                msg=f"{e}", 
                _input=entity
            )
        
    @classmethod
    def get_path_string(cls, path) -> str:
        parts = []
        current = path
        while current is not None:
            parts.append(str(current.key))
            current = current.prev
        return ".".join(reversed(parts)) 