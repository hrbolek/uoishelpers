import uuid
import typing
import datetime
import strawberry
import dataclasses
import json
import asyncio

from functools import cache
from .fromContext import getUserFromInfo

from .IDType import IDType

InputType = typing.TypeVar("GQLInputType")  

@strawberry.type(description="Error object returned as an result of Insert operation")
class InsertError(typing.Generic[InputType]):
    type_arg: strawberry.Private[object] = None  # Placeholder for the generic type argument

    msg: str = strawberry.field(default=None, description="reason of fail")
    _input: strawberry.Private[object]
    failed: bool = strawberry.field(default=True, description="always True, available when error")
    code: typing.Optional[IDType] = strawberry.field(default=None, description="error code, if available")
    location: typing.Optional[str] = strawberry.field(default=None, description="location of the error - resolver name")

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
        if dataclasses.is_dataclass(self._input):
            d = dataclasses.asdict(self._input)
            d_str = json.dumps(d, default=str)
            d = json.loads(d_str)
        else:
            # d = {key: f"{value}" if isinstance(value, (datetime.datetime, IDType)) else value for key, value in strawberry.asdict(self._input).items() if value is not None}
            d = {"raw": f"{self._input}"}
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
        entity_ = entity
        if isinstance(entity, InputModelMixin):
            entity_ = await entity.intoModel(info)
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
        

async def _convert(info, value):
    if hasattr(value, "intoModel"):
        return await value.intoModel(info)
    if isinstance(value, list):
        futures = [_convert(info, v) for v in value]
        result = await asyncio.gather(*futures)
        return result
    return value

async def intoModel(self, info: strawberry.types.Info):
    loader = self.getLoader(info=info)
    model = loader.getModel()
    instance = model()
    # TODO: asyncio.gather(*futures)
    for key in self.__annotations__.keys():
        original = getattr(self, key)
        converted = await _convert(info, original)
        setattr(instance, key, converted)
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

    def set_rbacobject_id(self, rbacobject_id):
        self.set_rbacobject_id_recursively(self, rbac_id=rbacobject_id)

    def set_rbacobject_id_recursively(self, obj, rbac_id, visited=None):
        if visited is None:
            visited = set()

        if obj is None or obj.id in visited:
            return

        visited.add(obj.id)

        # Nastavíme rbacobject_id pokud existuje
        if hasattr(obj, "rbacobject_id"):
            setattr(obj, "rbacobject_id", rbac_id)

        if not dataclasses.is_dataclass(obj):
            return

        for field in dataclasses.fields(obj):
            value = getattr(obj, field.name, None)

            if isinstance(value, list):
                for item in value:
                    if dataclasses.is_dataclass(item):
                        self.set_rbacobject_id_recursively(item, rbac_id, visited)

            elif dataclasses.is_dataclass(value):
                self.set_rbacobject_id_recursively(value, rbac_id, visited)

    async def intoModel(self, info: strawberry.types.Info):
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
            converted = await _convert(info, original)
            setattr(instance, key, converted)
        return instance
    
from sqlalchemy.orm import Session    
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
    
    async def intoModel(self, info: strawberry.types.Info):
        result = await super().intoModel(info)
        loader = self.getLoader(info=info)

        async def buildTreeStructure(instance, current_path=None, _visited=None):
            DBModel = type(instance)
            if _visited is None:
                _visited = set()
            if instance.id in _visited:
                return  # ochrana proti cyklení
            _visited.add(instance.id)
            # Pokud je current_path None, nastav na path rodiče nebo na None (pokud není rodič)
            if current_path is None:
                # Získej path nadřazené skupiny (nebo None, pokud žádná není)
                parent = getattr(instance, DBModel.parent_attribute_name, None)
                parent_id = getattr(instance, DBModel.parent_id_attribute_name, None)
                if parent:
                    current_path = getattr(parent, DBModel.path_attribute_name, None)
                elif parent_id:
                    parent = await loader.load(parent_id)
                    current_path = getattr(parent, DBModel.path_attribute_name, None) if parent else None
                else:
                    current_path = None
            # Nastav path pro aktuální instanci
            instance.path = f"{current_path}/{instance.id}" if current_path else str(instance.id)
            # Rekurzivně nastav path potomkům
            children = getattr(instance, DBModel.children_attribute_name, None)
            assert children is not None, "Children should not be None here, probably this method is used in operation other than insert."
            futures = []
            for child in children:
                if child is None:
                    continue
                if not isinstance(child, DBModel):
                    raise TypeError(f"Expected child of type {DBModel.__name__}, got {type(child).__name__}")
                futures.append(buildTreeStructure(child, instance.path, _visited=_visited))
            await asyncio.gather(*futures)
            return instance        

        if hasattr(result, "buildTreeStructure"):
            return await result.buildTreeStructure()
        else:
            assert hasattr(result, "parent_attribute_name"), f"Class {result.__class__.__name__} must have parent_attribute_name defined."
            assert hasattr(result, "path_attribute_name"), f"Class {result.__class__.__name__} must have path_attribute_name defined."
            assert hasattr(result, "children_attribute_name"), f"Class {result.__class__.__name__} must have children_attribute_name defined."
            assert hasattr(result, "parent_id_attribute_name"), f"Class {result.__class__.__name__} must have parent_id_attribute_name defined."
            return await buildTreeStructure(result, current_path=None, _visited=set())

        
