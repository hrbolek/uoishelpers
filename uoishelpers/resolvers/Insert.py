import uuid
import typing
import datetime
import strawberry

from functools import cache
from .fromContext import getUserFromInfo

from .IDType import IDType

InputType = typing.TypeVar("GQLInputType")  

@strawberry.type(description="Error object returned as an result of Insert operation")
class InsertError(typing.Generic[InputType]):
    msg: str = strawberry.field(default=None, description="reason of fail")
    _input: strawberry.Private[object]
    failed: bool = strawberry.field(default=True, description="always True, available when error")

    @strawberry.field(description="original data")
    def input(self) -> typing.Optional[strawberry.scalars.JSON]:
        if self._input is None:
            return None
        d = {key: f"{value}" if isinstance(value, (datetime.datetime, IDType)) else value for key, value in strawberry.asdict(self._input).items() if value is not None}
        return d

sentinel = "ea3afa47-3fc4-4d50-8b76-65e3d54cce01"
class Insert:
    
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
            # print(f"actinguser {actinguser}")
            id = IDType(actinguser["id"])
            # print(f"id {id}")
            rbacobject = getattr(entity, "rbacobject_id", sentinel)
            if rbacobject != sentinel:
                if rbacobject is None:
                    entity.rbacobject_id = id

            idvalue = getattr(entity, "id", sentinel)
            if idvalue is None:
                entity.id = uuid.uuid4()

            entity.createdby_id = id
            # print(f"entity {entity}")
            row = await loader.insert(entity)
            if row is None:
                return InsertError[type_arg](msg="insert failed", _input=entity)
            else:
                return await type_arg.resolve_reference(info=info, id=row.id)
        except Exception as e:
            return InsertError[type_arg](msg=f"{e}", _input=entity)        
        
