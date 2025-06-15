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
        entity_ = entity.intoModel(info) if isinstance(entity, InputModelMixin) else entity
        # entity_ = entity.intoModel(info) if hasattr(entity, "intoModel") else entity
        type_arg = cls.type_arg
        try:
            loader = type_arg.getLoader(info=info)
            actinguser = getUserFromInfo(info)
            # print(f"actinguser {actinguser}")
            id = IDType(actinguser["id"])
            # print(f"id {id}")
            rbacobject = getattr(entity_, "rbacobject_id", sentinel)
            if rbacobject != sentinel:
                if rbacobject is None:
                    entity_.rbacobject_id = id

            idvalue = getattr(entity_, "id", sentinel)
            if idvalue is None:
                entity_.id = uuid.uuid4()

            entity_.createdby_id = id
            # print(f"entity {entity}")
            row = await loader.insert(entity_)
            if row is None:
                return InsertError[type_arg](msg="insert failed", _input=entity_)
            else:
                return await type_arg.resolve_reference(info=info, id=row.id)
        except Exception as e:
            return InsertError[type_arg](msg=f"{e}", _input=entity_)        
        

def _convert(info, value):
    if hasattr(value, "intoModel"):
        return value.intoModel(info)
    if isinstance(value, list):
        return [_convert(info, v) for v in value]
    return value

def intoModel(self, info: strawberry.types.Info):
    loader = self.getLoader(info=info)
    model = loader.getModel()
    instance = model()
    for key in self.__annotations__.keys():
        original = getattr(self, key)
        setattr(instance, key, _convert(info, original))
    return instance


class InputModelMixin:
    """
    Mixin providing generic intoModel logic for all Strawberry input models.
    Subclasses must implement getLoader().
    """
    @classmethod
    def getLoader(cls, info: strawberry.types.Info):
        raise NotImplementedError(
            f"Class {cls.__name__} must implement getLoader()."
        )

    def intoModel(self, info: strawberry.types.Info):
        loader = self.getLoader(info)
        model_cls = loader.getModel()
        instance = model_cls()

        # … parsování ostatních polí …
        if self.id in (None, strawberry.UNSET):
            instance.id = uuid.uuid4()
        else:
            instance.id = self.id

        for key in self.__annotations__.keys():
            original = getattr(self, key)
            # Skip None values if desired
            if original is None:
                continue
            setattr(instance, key, _convert(info, original))
        return instance
    
class TreeInputStructureMixin(InputModelMixin):
    """
    Mixin providing generic tree structure logic for all Strawberry input models.
    Subclasses must implement getLoader().
    """
    @classmethod
    def getLoader(cls, info: strawberry.types.Info):
        raise NotImplementedError(
            f"Class {cls.__name__} must implement getLoader()."
        )
    
    def intoModel(self, info: strawberry.types.Info):
        result = super().intoModel(info)
        if hasattr(result, "buildTreeStructure"):
            return result.buildTreeStructure()
        else:
            raise NotImplementedError(
                f"Class {result.__class__.__name__} must implement buildTreeStructure()."
            )