import typing
import datetime
import strawberry

from .fromContext import getUserFromInfo

from .IDType import IDType

UpdateType = typing.TypeVar("GQLEntityType")    

@strawberry.federation.type(keys=["id"])
class UpdateError(typing.Generic[UpdateType]):
    _entity: typing.Optional[UpdateType] = strawberry.field(default=None, description="Entity to be updated")
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
class Update:
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
            actinguser = getUserFromInfo(info)
            id = IDType(actinguser["id"])
            entity.changedby_id = id

            row = await loader.update(entity)
            if row is None:
                # _entity = await loader.load(facility.id)
                _entity = await type_arg.resolve_reference(info=info, id=entity.id)
                return UpdateError[type_arg](_entity=_entity, msg="update failed", _input=entity)
            else:
                return await type_arg.resolve_reference(info=info, id=entity.id)
        except Exception as e:
            _entity = await type_arg.resolve_reference(info=info, id=entity.id)
            return UpdateError[type_arg](_entity=_entity, msg=f"{e}", _input=entity)
