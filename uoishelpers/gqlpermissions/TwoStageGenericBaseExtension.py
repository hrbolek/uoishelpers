import functools
import typing
import strawberry
from strawberry.extensions import FieldExtension

import typing

TErrorType = typing.TypeVar("ErrorType")
TGQLModel = typing.TypeVar("GQLModel")

class TwoStageGenericBaseExtension(FieldExtension, typing.Generic[TErrorType, TGQLModel]):
    GQLModel = None
    ErrorType = None

    @classmethod
    @functools.cache
    def __class_getitem__(cls, item):
        if cls.ErrorType is not None and cls.GQLModel is not None:
            raise Exception(f"Error is alredy defined as {cls.ErrorType} and model is already defined as {cls.GQLModel}")
        
        # Jestliže už máme ErrorType, a teď dostáváme item = GQLModel:
        if cls.ErrorType is not None and cls.GQLModel is None:
            # Tady nastavíme model a vrátíme novou třídu
            new_cls = type(
                f"{cls.__name__}[{cls.ErrorType.__name__}_{item.__name__}]",
                (cls,),
                {"ErrorType": cls.ErrorType, "GQLModel": item},
            )
            return new_cls
        

        # Jinak máme item jako:
        # 1) tuple(ErrorType, GQLModel)
        # 2) ErrorType[GQLModel]
        # 3) jen ErrorType

        if isinstance(item, tuple) and len(item) == 2:
            error_type, gql_model = item
        else:
            origin = getattr(item, "__origin__", None)
            args = getattr(item, "__args__", ())
            if origin is not None and args:
                error_type = origin
                gql_model = args[0]
            else:
                # Jen ErrorType (další parametr bude dodán později)
                error_type = item
                gql_model = None

        new_cls = type(
            f"{cls.__name__}[{error_type.__name__}{'_' + gql_model.__name__ if gql_model else ''}]",
            (cls,),
            {"ErrorType": error_type, "GQLModel": gql_model},
        )
        return new_cls
    
    def get_path_string(self, path) -> str:
        parts = []
        current = path
        while current is not None:
            parts.append(str(current.key))
            current = current.prev
        return ".".join(reversed(parts))
    
    def return_error(self, info: strawberry.types.Info, message: str, code: str, input_data: typing.Any = None):
        error_description = {
            "msg": message,
            "code": code,
            "_input": input_data or {},
            "location": self.get_path_string(info.path) if hasattr(info, "path") and info.path else None
        }
        info.context["errors"].append(error_description)
        return self.ErrorType[self.GQLModel](**error_description)
