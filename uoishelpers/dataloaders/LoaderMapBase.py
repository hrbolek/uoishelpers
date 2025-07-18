from .IDLoader import IDLoader


import typing
import functools
from typing import Type, Dict

T = typing.TypeVar("T")
class LoaderMapBase(typing.Generic[T]):
    BaseModel: Type[T] = None

    @classmethod
    @functools.cache
    def __class_getitem__(cls, item):
        # Vrací novou podtřídu s přednastaveným .model
        name = f"{cls.__name__}[{item.__name__}]"
        return type(
            name,
            (cls,),
            {"BaseModel": item}
        )

    def __init__(self, session):
        BaseModel = type(self).BaseModel
        self.session = session
        self._all: Dict[typing.Any, IDLoader] = {
            DBModel.class_: IDLoader[DBModel.class_](session)
            for DBModel in BaseModel.registry.mappers
        }        

    def get(self, model: Type[T]) -> IDLoader[T]:

        if isinstance(model, str):
            BaseModel = type(self).BaseModel
            model = next(
                (m.class_ for m in BaseModel.registry.mappers if m.class_.__name__ == model),
                None
            )
            print(f"gettin model by name: {model}")
            # model = BaseModel.registry.get(model)
        result = self._all.get(model)
        if result is None:
            print(f"Creating new IDLoader for model: {model}")
            result = IDLoader[model](self.session)
            self._all[model] = result
        return result  
