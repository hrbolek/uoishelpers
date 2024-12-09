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
    failed: bool = strawberry.field(default=True, description="always True, available when error")
    _input: strawberry.Private[object]

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
                    return DeleteError[type_arg](_entity=_entity, msg=f"Someone changed entity", _input=entity)
            await loader.delete(entity.id)
            return None
        except Exception as e:
            _entity = await type_arg.resolve_reference(info=info, id=entity.id)
            return DeleteError[type_arg](_entity=_entity, msg=f"{e}", _input=entity)
