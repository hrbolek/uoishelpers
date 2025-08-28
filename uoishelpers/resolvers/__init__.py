import uuid
import dataclasses
import json
import sqlalchemy
import strawberry  # strawberry-graphql==0.119.0

from sqlalchemy import inspect
from sqlalchemy.orm import ColumnProperty
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm.relationships import Relationship
import strawberry.types
from strawberry.utils.inspect import get_func_args
from functools import cache
from typing import cast

import datetime
from typing import Any, Coroutine, Callable, Awaitable, Union, List, Optional

from sqlalchemy.future import select
from sqlalchemy import delete
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.declarative import DeclarativeMeta as BaseModel

from contextlib import asynccontextmanager

import typing
import logging
import sys

from .IDType import IDType
from .Insert import Insert, InsertError, InputModelMixin, TreeInputStructureMixin
from .Update import Update, UpdateError
from .Delete import Delete, DeleteError
from .fromContext import getLoadersFromInfo, getUserFromInfo, getUgClientFromInfo
from .PageResolver import PageResolver
from .VectorResolver import VectorResolver
from .ScalarResolver import ScalarResolver

@asynccontextmanager
async def withInfo(info):
    """Context manager for session created
    from info.context['asyncSessionMaker']."""
    asyncSessionMaker = info.context["asyncSessionMaker"]
    async with asyncSessionMaker() as session:
        try:
            yield session
        finally:
            pass


inputTypeGQLMapper = {}

def get_field_or_default(source_cls, name, default_field):
    """
    Pokud má původní třída source_cls na attributu name definovaný
    dataclasses.Field (tedy strawberry.field), vrať ho; jinak default_field.
    """
    val = getattr(source_cls, name, None)
    if isinstance(val, dataclasses.Field):
        return val
    return default_field

def remap_examples(examples: list[dict], field: str) -> list[dict]:
    """
    Pro každý původní příklad {orig_field: {...}}
    vrátí nový příklad {field: {...}}
    """
    new = []
    for ex in examples:
        # vytáhnu hodnotu jediného klíče
        value = next(iter(ex.values()))
        new.append({field: value})
    return new

def remap_examples2(cls, for_field: str) -> list[dict]:
    """
    Pro každý původní příklad {orig_field: {...}}
    vrátí nový příklad {field: {...}}
    """

    dc_fields = getattr(cls, "__dataclass_fields__", {})
    
    if "examples" in dc_fields:
        meta = dc_fields["examples"]
        # zavoláme default_factory, pokud existuje, jinak default
        if meta.default_factory is not dataclasses.MISSING:
            raw = meta.default_factory()
        else:
            raw = meta.default if meta.default is not dataclasses.MISSING else []
    else:
        raw = []    

    # privates = getattr(cls, "_type_definition", None)
    # if privates is None:
    #     return []
    # pf = next(
    #     f for f in privates.private_fields
    #         if f.python_name == "examples"
        
    # )
    # if pf is None:
    #     return None
    return remap_examples(raw, for_field)

def build_description_from_input(baseType: type) -> str:
    from strawberry.types.lazy_type import LazyType

    if typing.get_origin(baseType) is typing.Annotated:
        # první argument je typ nebo ForwardRef
        inner, *metadata = typing.get_args(baseType)
        # metadata může obsahovat LazyType
        for meta in metadata:
            if isinstance(meta, LazyType):
                return build_description_from_input(meta.resolve_type())
        # pokud žádný LazyType, prostě pokračujeme na ten inner
        return build_description_from_input(inner)
        
    # --- 1) Rozbalení strawberry.lazy.LazyType ---
    if isinstance(baseType, LazyType):
        # resolve_type() vrací skutečný typ
        real_type = baseType.resolve_type()
        return build_description_from_input(real_type)
    
    # 1) Ošetření ForwardRef
    if isinstance(baseType, typing.ForwardRef):
        # a) vratíme jen jméno, placeholder
        type_name = baseType.__forward_arg__
        return f"Filter for `{type_name}` (forward reference)."
        #
        # -- nebo b) pokud znáte slovníky jmen, můžete zkusit vyhodnotit:
        # resolved = eval(type_name, globalns or globals(), localns or locals())
        # return build_description_from_input(resolved, globalns, localns)
        # 

    # Přistoupíme k metadatech Strawberry
    type_def = baseType._type_definition
    
    # Pro každý field vytáhneme jméno a existující popisek
    lines = []
    for f in type_def.fields:
        # f.python_name je název v kódu, f.name je název v SDL (pokud se liší)
        name: str = f.python_name
        if name.startswith("_"):
            continue
        desc = f.description or ""
        # lines.append(f"- **{name}**: {desc}")
        lines.append(f"**{name}**: filter for field {name}")

    # Sestavíme finální dlouhý popisek
    full_desc = (
        # "BLA BLA"+
        # f"{type_def.description or ''}\n\n"
        # "Fields:\n" +
        ", ".join(lines)
    )
    print(f"reading description for {type_def}:\n{full_desc}")
    return full_desc

def createInputs(arg=None, *, v2: bool = False):
    """
    Decoder decorator: @createInputs  nebo  @createInputs(v2=True)

    Pokud v2=True, použije createInputs2 a ověří, že cls ještě není dataclass.
    Jinak zavolá původní createInputs_old.
    """
    def _decorate(cls):
        if v2:
            # u nové verze je třeba ji aplikovat **před** @dataclass
            if dataclasses.is_dataclass(cls):
                raise TypeError(
                    "createInputs(v2=True) must wrap the plain class, not an already-@dataclass class"
                )
            return createInputs2(cls)
        else:
            return createInputs_old(cls)

    # případ bez závorek: @createInputs
    if arg is not None and isinstance(arg, type):
        return _decorate(arg)

    # případ s (možnými) parametry: @createInputs(...)  
    return _decorate

def createInputs2(cls):
    """
    Dekorátor nad @dataclass, který pro každý field v cls.__annotations__
    vygeneruje odpovídající filter-input typ a pak 'where', 'and' a 'or' typy.
    Pokud už máš u původní dataclassi k field strawberry.field(...),
    zachová ho a nepřepíše.
    """
    clsname = cls.__name__
    module_path = cls.__module__
    whereName = clsname
    orName    = f"{clsname}_or"
    andName   = f"{clsname}_and"

    fieldNames = list(cls.__annotations__.keys())
    types_     = list(cls.__annotations__.values())
    cls__annotations__ = cls.__annotations__

    customInputs = []
    customInputsDict = {}

    from typing import get_origin, get_args, Optional, List, Union, Tuple, Set, Annotated, ForwardRef
    import types
    from strawberry import LazyType
    NoneType = type(None)
    # def unwrap(t):
    #     # strip Annotated[T, ...]
    #     if get_origin(t) is Annotated:
    #         t = get_args(t)[0]
    #         return unwrap(t)

    #     o = get_origin(t)

    #     # Optional / Union / PEP604 unions
    #     if o in (Union, types.UnionType):
    #         args = [a for a in get_args(t) if a is not NoneType]
    #         if len(args) == 1:
    #             return unwrap(args[0])      # Optional[T] -> T
    #         # heterogenní union (A|B) – nevíme zvolit jediný typ, vrať jak je
    #         return t

    #     # Kolekce: List[T], Set[T]
    #     if o in (list, List, set, Set):
    #         (inner,) = get_args(t) or (object,)
    #         return unwrap(inner)

    #     # Tuple[...] – variadické vs heterogenní
    #     if o in (tuple, Tuple):
    #         args = get_args(t)
    #         if len(args) == 2 and args[1] is Ellipsis:   # Tuple[T, ...]
    #             return unwrap(args[0])
    #         if len(args) == 1:                           # Tuple[T]
    #             return unwrap(args[0])
    #         return t                                     # heterogenní tuple – necháme být

    #     # ForwardRef apod. – necháme být; vyřeší se později
    #     return t
    # print(f"description of {clsname}\n{cls.__dataclass_fields__}")
    # 1) Projdeme každé pole a vyrobíme mu vlastní Input typ
    for field, baseType in zip(fieldNames, types_):
        # Pokud už máme mapování pro baseType, použijeme ho
        # base = unwrap(baseType)
        base = baseType
        # existing = inputTypeGQLMapper.get(baseType)
        existing = inputTypeGQLMapper.get(base)
        original = getattr(cls, field, None)
        if existing:
            customInputs.append(existing)
            customInputsDict[field] = existing
            continue

        customInputsDict[field] = Optional[base]

    # 2) Sestavíme slovník fieldName → jeho Input typ pro další operátory
    print(f"{clsname}: customInputsDict = {customInputsDict}")
    # v teto chvili customInputs ma vsechny pridane filtry v poradi odpovidajici fieldNames

    # 3) Helper na vytvoření 'or', 'and' i samotného 'where'
    def buildOpType(typeName: str, extra: dict):
        Op = type(typeName, (), {})

        annotations = { **extra, **customInputsDict }
        Op.__annotations__ = annotations
        
        field_descriptions = {}
        for op_field, annotation in annotations.items():
            examples = []
            desc = ""
            if op_field == "_and":
                desc = (
                    "Logical AND of multiple filters. "
                    "All child filters must match."
                )
            elif op_field == "_or":
                desc = (
                    "Logical OR of multiple filters. "
                    "At least one child filter must match."
                )
            # elif op_field == whereName:
            #     pass
            else:
                Op.__annotations__[op_field] = typing.Optional[annotation] # marking filter as Optional
                __strawberry_definition__ = getattr(annotation, "__strawberry_definition__", None)
                if __strawberry_definition__:
                    desc: str = annotation.__strawberry_definition__.description
                else:
                    field = getattr(cls, op_field, None)
                    if field is not None:
                        desc: str = getattr(field, "description", "compound filter")
                    # desc: str = "compound filter"
                # print(f"annotation {annotation}", flush=True)

            # new_examples = []
            # print(f"{clsname}: desc = {desc}")
                
            field_descriptions[op_field] = desc

            default_field = get_field_or_default(
                cls, op_field,
                strawberry.field(name=op_field, description=desc, default=None)
            )
            setattr(Op, op_field, default_field)

        # Sestavíme společný description pro celý typ
        all_fields_md = ""
        for field_name, field_type in customInputsDict.items():
            print(f"scanning {field_name}: {field_type}")
            
            examples_description = ""
            example_count = 0
            __strawberry_definition__ = getattr(field_type, "__strawberry_definition__", None)
            if __strawberry_definition__:
                for filter_field in field_type.__strawberry_definition__.fields:
                    example = filter_field.metadata.get("example", None)     
                    if example is None:
                        continue   
                    example_count += 1
                    if isinstance(example, list):
                        renamed_example = example
                    else:
                        renamed_example = {field_name: op for op in example.values()}
                    examples_description += f"\n\t {json.dumps(renamed_example)}"
                    # print(f"{field_name}: {filter_field}: {renamed_example}")
                    pass
            if example_count:
                pass
            if examples_description:
                all_fields_md += f"\n- **{field_name}** filter, examples:\n{examples_description}"
            else:
                description = "compound sub filter"
                field = getattr(cls, field_name, None)
                if field is not None:
                    description = getattr(field, "description", description)

                all_fields_md += f"\n- **{field_name}** {description}"
        # all_fields_md = "\n".join(
        #     f"- **{name}**: {desc}"
        #     for name, desc in field_descriptions.items()
        # )
        # TODO zvazit jsdoc like description, pripadnej jiny standard
        full_description = (
            f"Compound filter encapsulating subfilters on fields:\n" +
            all_fields_md +
            "\n\n"
            "Subfilters "
            "can be nested via `_and` and `_or`. `_and` can nest only `_or`, while `_or` can nest only `_and`\n"
            "_and can be a list of subfilters, all of them must be satisfied\n"
            "_or can be a list of subfilters, one of them must be satisfied\n"
        )
        # full_description = ""
        return strawberry.input(
            Op,
            name=typeName,
            description=full_description
        )

    orOp = buildOpType(orName, {"_and": typing.Optional[typing.List[andName]]})
    andOp = buildOpType(andName, {"_or": typing.Optional[typing.List[orName]]})
    whereOp = buildOpType(
        whereName,
        {
            "_or":  typing.Optional[typing.List[orName]],
            "_and": typing.Optional[typing.List[andName]],
        }
    )
    whereOpLazy = Annotated[whereName, strawberry.lazy(module_path)]
    inputTypeGQLMapper[cls] = whereOpLazy
    # 4) Exportujeme všechny nově vytvořené typy do modulu, kde byla dataclass
    mod = sys.modules[__name__]
    for type_ in [whereOp, andOp, orOp, *customInputs]:
        setattr(mod, type_.__name__, type_)

    return whereOp

def createInputs_old(cls):
    """
    Dekorátor nad @dataclass, který pro každý field v cls.__annotations__
    vygeneruje odpovídající filter‑input typ a pak 'where', 'and' a 'or' typy.
    Pokud už máš u původní dataclassi k field strawberry.field(...),
    zachová ho a nepřepíše.
    """

    clsname = cls.__name__
    # print(f"GQL definitions for {clsname}")
    # whereName = clsname + "_where"
    whereName = clsname
    orName = clsname + "_or"
    andName = clsname + "_and"

    fieldNames = [field_name for field_name in cls.__annotations__]
    opNames = [clsname + "_" + field_name for field_name in fieldNames]
    types = [field for field in cls.__annotations__.values()]

    def createCustomInput(field, name, baseType = str):
        result = inputTypeGQLMapper.get(baseType, None)
        if result is None:
            # print(30*"#")
            # print(f"New GQL type for {baseType.__name__}")
            if (baseType.__name__ == typing.Annotated.__name__):
                # print(30*"#", "Annotated")
                return baseType
            logging.info(f"New GQL type for {baseType}")
            # print(f"New GQL type for {baseType}")
            result = type(name, (object,), {})
            result.__annotations__ = {
                op: typing.Optional[baseType] for op in ["_eq", "_le", "_lt", "_ge", "_gt"]
            }
            for op in ["_eq", "_le", "_lt", "_ge", "_gt"]:
                setattr(result, op, strawberry.field(name=op, description="operation for select.filter() method", default=None))           
            result = strawberry.input(result, description=f"Expression on attribute '{field}'. Only one constrain allowed.")
        else:
            logging.info(f"Using GQL type for {(baseType)} ({result})")
            # print(f"Using GQL type for {(baseType)} ({result})")
        return   result

    inputTypes = [
        createCustomInput(field, name, baseType)
        for field, name, baseType in zip(fieldNames, opNames, types)
    ]
    
    inputTypesDict = {
        fieldName: typing.Optional[inputType]
        for fieldName, inputType in zip(fieldNames, inputTypes)
    }

    #print("inputTypesDict")
    #print(inputTypesDict)

    def createOr():
        result = type(orName, (object,), {})
        anotations = {
            "_and": typing.Optional[typing.List[andName]],
            **inputTypesDict
        }
        result.__annotations__ = anotations
        for op in anotations.keys():
            setattr(result, op, 
                strawberry.field(name=op, description="Filter method", default=None)
            )
        return result  
        
    orOp = strawberry.input(createOr(), description=f"Or operator definition on {clsname}")
    #print("orOp")
    #print(orOp)

    def createAnd():
        result = type(andName, (object,), {})
        anotations = {
            "_or": typing.Optional[typing.List[orName]],
            **inputTypesDict
        }
        result.__annotations__ = anotations
        for op in anotations.keys():
            setattr(result, op, 
                strawberry.field(name=op, description="Filter method", default=None)
            )
        return result

    andOp = strawberry.input(createAnd(), description=f"And operator definition on {clsname}")
    #print("andOp")
    #print(andOp)

    def createWhereOp():
        result = type(whereName, (object,), {})
        anotations = {
            # "_or": typing.Optional[typing.List[orOp]],
            # "_and": typing.Optional[typing.List[andOp]],
            # "_or": typing.Optional[typing.List[f'"{orName}"']],
            # "_and": typing.Optional[typing.List[f'"{andName}"']],
            "_or": typing.Optional[typing.List[orName]],
            "_and": typing.Optional[typing.List[andName]],
            **inputTypesDict
        }
        result.__annotations__ = anotations
        for op in anotations.keys():
            setattr(result, op, 
                strawberry.field(name=op, description="Filter method", default=None)
            )
            
        return result  

    whereOp = strawberry.input(createWhereOp(), description=f"Operators definition on {clsname}")
    #print("topOp")
    #print(topOp)
       
    ####################################
    # make all ops global in this module
    ####################################
    result = [whereOp, andOp, orOp, *inputTypes]
    this = sys.modules[__name__]
    for r in result:
        setattr(this, r.__name__, r)

    #return [topOp, andOp, orOp, *inputTypes]

    #register new type
    inputTypeGQLMapper[whereOp] = whereOp
    return whereOp
    #return inputTypes

@strawberry.input(description='''Str filter operators, 
for field "name" the filters can be 
{"name": {"_eq": "Peter"}}
{"name": {"_ge": "A"}}
{"name": {"_gt": "E"}}
{"name": {"_le": "Z"}}
{"name": {"_lt": "F"}}
{"name": {"_ilike": "%ete%"}}
{"name": {"_like": "Pet%"}}
{"name": {"_startswith": "Pet"}}
{"name": {"_endswith": "ter"}}
''')
class StrFilter:
    _eq: typing.Optional[str] = strawberry.field(
        name="_eq", 
        description='filter aka {"name": {"_eq": "Peter"}}', 
        default=None,
        metadata={"example": {"name": {"_eq": "Peter"}}}
    )
    _le: typing.Optional[str] = strawberry.field(
        name="_le", 
        description='filter aka {"name": {"_ge": "A"}}', 
        default=None,
        metadata={"example": {"name": {"_ge": "A"}}}
    )
    _lt: typing.Optional[str] = strawberry.field(
        name="_lt", 
        description='filter aka {"name": {"_lt": "F"}}', 
        default=None,
        metadata={"example": {"name": {"_lt": "F"}}}
    )
    _ge: typing.Optional[str] = strawberry.field(
        name="_ge", 
        description='filter aka {"name": {"_ge": "A"}}', 
        default=None,
        metadata={"example": {"name": {"_ge": "A"}}}
    )
    _gt: typing.Optional[str] = strawberry.field(
        name="_gt", 
        description='filter aka {"name": {"_gt": "E"}}', 
        default=None,
        metadata={"example": {"name": {"_gt": "E"}}}
    )
    _like: typing.Optional[str] = strawberry.field(
        name="_like", 
        description='filter aka {"name": {"_like": "Pet%"}}', 
        default=None,
        metadata={"example": {"name": {"_like": "Pet%"}}}
    )
    _ilike: typing.Optional[str] = strawberry.field(
        name="_ilike", 
        description='filter aka {"name": {"_like": "Pet%"}}', 
        default=None,
        metadata={"example": {"name": {"_like": "Pet%"}}}
    )
    _startswith: typing.Optional[str] = strawberry.field(
        name="_startswith", 
        description='filter aka {"name": {"_startswith": "Pet"}}', 
        default=None,
        metadata={"example": {"name": {"_startswith": "Pet"}}}
    )
    _endswith: typing.Optional[str] = strawberry.field(
        name="_endswith", 
        description='filter aka {"name": {"_endswith": "ter"}}', 
        default=None,
        metadata={"example": {"name": {"_endswith": "ter"}}}
    )
    
    # examples: strawberry.Private[typing.List[dict]] = dataclasses.field(
    #     default_factory=lambda: [
    #     {"name": {"_eq": "Peter"}},
    #     {"name": {"_ge": "A"}},
    #     {"name": {"_gt": "E"}},
    #     {"name": {"_le": "Z"}},
    #     {"name": {"_lt": "F"}},
    #     {"name": {"_ilike": "%ete%"}},
    #     {"name": {"_like": "Pet%"}},
    #     {"name": {"_startswith": "Pet"}},
    #     {"name": {"_endswith": "ter"}}
    # ])

@strawberry.input(description='''Datetime filter operators, 
for field "lastchange" the filters can be 
{"lastchange": {"_eq": "2025-06-30T18:01:59"}}
{"lastchange": {"_ge": "2025-06-30T18:01:59"}}
{"lastchange": {"_gt": "2025-06-30T18:01:59"}}
{"lastchange": {"_le": "2025-06-30T18:01:59"}}
{"lastchange": {"_lt": "2025-06-30T18:01:59"}}
''')
class DatetimeFilter:
    _eq: typing.Optional[datetime.datetime] = strawberry.field(
        name="_eq", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"lastchange": {"_eq": "2025-06-30T18:01:59"}}}
    )
    _le: typing.Optional[datetime.datetime] = strawberry.field(
        name="_le", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"lastchange": {"_le": "2025-06-30T18:01:59"}}}
    )
    _lt: typing.Optional[datetime.datetime] = strawberry.field(
        name="_lt", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"lastchange": {"_lt": "2025-06-30T18:01:59"}}}
    )
    _ge: typing.Optional[datetime.datetime] = strawberry.field(
        name="_ge", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"lastchange": {"_ge": "2025-06-30T18:01:59"}}}
    )
    _gt: typing.Optional[datetime.datetime] = strawberry.field(
        name="_gt", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"lastchange": {"_gt": "2025-06-30T18:01:59"}}}
    )
    # examples: strawberry.Private[typing.List[dict]] = dataclasses.field(
    #     default_factory=lambda: [
    #     {"lastchange": {"_eq": "2025-06-30T18:01:59"}},
    #     {"lastchange": {"_ge": "2025-06-30T18:01:59"}},
    #     {"lastchange": {"_gt": "2025-06-30T18:01:59"}},
    #     {"lastchange": {"_le": "2025-06-30T18:01:59"}},
    #     {"lastchange": {"_lt": "2025-06-30T18:01:59"}}
    # ])

@strawberry.input(description='''Timeduration filter operators, 
for field "duration" the filters can be 
{"duration": {"_eq": 1}}
{"duration": {"_ge": 1}}
{"duration": {"_gt": 1}}
{"duration": {"_le": 1}}
{"duration": {"_lt": 1}}
''')
class TimeDurationFilter:
    _eq: typing.Optional[datetime.timedelta] = strawberry.field(
        name="_eq", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"duration": {"_eq": 1}}}
    )
    _le: typing.Optional[datetime.timedelta] = strawberry.field(
        name="_le", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"duration": {"_le": 1}}}
    )
    _lt: typing.Optional[datetime.timedelta] = strawberry.field(
        name="_lt", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"duration": {"_lt": 1}}}
    )
    _ge: typing.Optional[datetime.timedelta] = strawberry.field(
        name="_ge", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"duration": {"_ge": 1}}}
    )
    _gt: typing.Optional[datetime.timedelta] = strawberry.field(
        name="_gt", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"duration": {"_gt": 1}}}
    )
    # examples: strawberry.Private[typing.List[dict]] = dataclasses.field(
    #     default_factory=lambda: [
    #     {"duration": {"_eq": 1}},
    #     {"duration": {"_ge": 1}},
    #     {"duration": {"_gt": 1}},
    #     {"duration": {"_le": 1}},
    #     {"duration": {"_lt": 1}}
    # ])

@strawberry.input(description='''Integer filter operators, 
for field "age" the filters can be 
{"age": {"_eq": 1}}
{"age": {"_ge": 1}}
{"age": {"_gt": 1}}
{"age": {"_le": 1}}
{"age": {"_lt": 1}}
''')
class IntFilter:
    _eq: typing.Optional[int] = strawberry.field(
        name="_eq", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"age": {"_eq": 1}}}
    )
    _le: typing.Optional[int] = strawberry.field(
        name="_le", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"age": {"_le": 1}}}
    )
    _lt: typing.Optional[int] = strawberry.field(
        name="_lt", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"age": {"_lt": 1}}}
    )
    _ge: typing.Optional[int] = strawberry.field(
        name="_ge", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"age": {"_ge": 1}}}
    )
    _gt: typing.Optional[int] = strawberry.field(
        name="_gt", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"age": {"_gt": 1}}}
    )
    _in: typing.Optional[typing.List[int]] = strawberry.field(
        name="_in", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"age": {"_in": 1}}}
    )
    # examples: strawberry.Private[typing.List[dict]] = dataclasses.field(
    #     default_factory=lambda: [
    #     {"age": {"_eq": 1}},
    #     {"age": {"_ge": 1}},
    #     {"age": {"_gt": 1}},
    #     {"age": {"_le": 1}},
    #     {"age": {"_lt": 1}}
    # ])

@strawberry.input(description='''Boolean filter operators, 
for field "valid" the filters can be 
{"valid": {"_eq": true}}
''')
class BoolFilter:
    _eq: typing.Optional[bool] = strawberry.field(
        name="_eq", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"valid": {"_eq": True}}}
    )
    # examples: strawberry.Private[typing.List[dict]] = dataclasses.field(
    #     default_factory=lambda: [
    #     {"valid": {"_eq": True}}
    # ])

import uuid
uuid.UUID
@strawberry.input(description='''UUID filter operators, 
for field "id" the filters can be 
{"id": {"_eq": "5fa97795-454e-4631-870e-3f0806018755"}}
{"id": {"_in": ["5fa97795-454e-4631-870e-3f0806018755", "011ec2bc-a0b9-44f3-bcd8-a42691eebaa4"]}}
''')
class UuidFilter:
    _eq: typing.Optional[uuid.UUID] = strawberry.field(
        name="_eq", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"id": {"_eq": "5fa97795-454e-4631-870e-3f0806018755"}}}
    )
    _in: typing.Optional[typing.List[uuid.UUID]] = strawberry.field(
        name="_in", 
        description="operation for select.filter() method", 
        default=None,
        metadata={"example": {"id": {"_in": ["5fa97795-454e-4631-870e-3f0806018755", "011ec2bc-a0b9-44f3-bcd8-a42691eebaa4"]}}}
    )
    # examples: strawberry.Private[typing.List[dict]] = dataclasses.field(
    #     default_factory=lambda: [
    #     {"id": {"_eq": "5fa97795-454e-4631-870e-3f0806018755"}},
    #     {"id": {"_in": ["5fa97795-454e-4631-870e-3f0806018755", "011ec2bc-a0b9-44f3-bcd8-a42691eebaa4"]}}
    # ])

inputTypeGQLMapper[uuid.UUID] = UuidFilter
inputTypeGQLMapper[int] = IntFilter
inputTypeGQLMapper[str] = StrFilter
inputTypeGQLMapper[datetime.datetime] = DatetimeFilter
inputTypeGQLMapper[bool] = BoolFilter
inputTypeGQLMapper[datetime.timedelta] = TimeDurationFilter


def update(destination, source=None, extraValues={}):
    """Updates destination's attributes with source's attributes.
    Attributes with value None are not updated."""
    if source is not None:
        for name in dir(source):
            if name.startswith("_"):
                continue
            value = getattr(source, name)
            if value is not None:
                setattr(destination, name, value)

    for name, value in extraValues.items():
        setattr(destination, name, value)

    return destination


async def putSingleEntityToDb(session, entity):
    """Asynchronně uloží entitu do databáze,
    entita musí být definována jako instance modelu (SQLAlchemy)"""
    async with session.begin():
        session.add(entity)
    await session.commit()
    return entity


def createFilterInputType(rootName, names=[]):
    assert not (len(names) == 0), "There must be some names"
    # {'where': {'_or': [{'name': {'_eq': 5}}, {'name': {'_eq': 4}}]}}

    def createCustomInput(attributeName):
        result = type(f"{rootName}By_{attributeName}", (object,), {})
        result.__annotations__ = dict(
            (op, Optional[str]) for op in ["_eq", "_le", "_lt", "_ge", "_gt"]
        )
        for op in ["_eq", "_le", "_lt", "_ge", "_gt"]:
            setattr(result, op, None)
        return strawberry.input(result)  # this is decoration

    customInputFilters = dict(
        (name, createCustomInput(name))
        for name in names)

    AllAttributes = type(f"{rootName}AllAttributes", (object,), {})
    for name in names:
        setattr(AllAttributes, name, None)
    AllAttributes.__annotations__ = dict(
        (name, Optional[customInputFilters[name]]) for name in names
    )
    AllAttributes = strawberry.input(AllAttributes)

    Filter = type(f"{rootName}Filter", (object,), {})
    Filter.__annotations__ = {
        "_or": Optional[List[AllAttributes]],
        "_and": Optional[List[AllAttributes]],
        **dict((name, Optional[customInputFilters[name]]) for name in names),
    }
    Filter._or = None
    Filter._and = None
    for name in names:
        setattr(Filter, name, None)
    Filter = strawberry.input(Filter)

    return Filter


def createEntityGetterWithFilter(DBModel: BaseModel):

    stmt = select(DBModel)
    mapper = sqlalchemy.inspect(DBModel)

    columnTypes = dict(
        (item.columns[0].type, item.columns[0].name)
        for item in mapper.column_attrs
    )

    def createOrLambda(query):
        pass

    def createNamedLambda(query):
        # for queryName, queryValue in query.items():
        #    break # decomposition, hack, get first key and its value

        queryName = None
        for key, value in columnTypes.items():
            if hasattr(query, key):
                queryName = key
                break

        methodMaps = {
            "_eq": "__eq__",
            "_gt": "__gt__",
            "_lt": "__lt__",
            "_ge": "__ge__",
            "_le": "__le__",
        }

        foundValue = None
        if not (queryName is None):
            foundValue = getattr(query, queryName)

            comparedItem = None
            for key, value in methodMaps.items():
                if hasattr(foundValue, key):
                    comparedItem = value
                    break

            return getattr(DBModel, methodMaps[key])(comparedItem)

        return DBModel.id == DBModel.id  # will this work?

    def createWhereLambda(where):
        pass

    async def FullResolver(
        session, skip: Optional[int] = 0, limit: Optional[int] = 10, where=None
    ) -> List[DBModel]:
        stmtWithFilter = stmt.offset(skip).limit(limit)
        dbSet = await session.execute(stmtWithFilter)
        result = dbSet.scalars()
        return result

    return FullResolver


def createEntityGetterWR(
    DBModel: BaseModel, options=None, redis=None
) -> Callable[[AsyncSession, int, int], Awaitable[Union[BaseModel, None]]]:
    """Předkonfiguruje dotaz do databáze na vektor entit

    Parameters
    ----------
    DBModel : BaseModel
        class representing SQLAlchlemy model - table where record will be found
    options : any
        possible to use joinedload from SQLAlchemy
        for extending the query (select with join)

    Returns
    -------
    Callable[[AsyncSession, int, int], Awaitable[DBModel]]
        asynchronous function for query into database
    """
    assert options is None, "options cannot be used"
    assert redis is not None, "redis must be defined"

    stmt = select(DBModel)

    mapper = sqlalchemy.inspect(DBModel)
    columnNames = dict(
        (item.columns[0].name, item.columns[0].type)
        for item in mapper.column_attrs
    )

    print(columnNames)

    predefinedSerialisers = {
        sqlalchemy.Boolean: lambda value: f"{value}",
        sqlalchemy.String: lambda value: value,
        sqlalchemy.DateTime: lambda value: f"{value}",
        uuid.UUID: lambda value: f"{value}",
        sqlalchemy.BigInteger: lambda value: value,
    }

    serialisers = {}
    for colName, colType in columnNames.items():
        serialisers[colName] = predefinedSerialisers.get(
            colType, lambda value: f"{value}"
        )

    def convertModelToJSON(model: DBModel):
        result = dict(
            (name, serialisers[name](getattr(model, name)))
            for name in columnNames.keys()
        )
        return result

    def convertJSONToModel(jsonData):
        result = DBModel()
        for columnName, columnType in columnNames.items():
            setattr(
                columnName,
                serialisers[columnName](jsonData.get(columnName, None))
            )
        return result

    def envelopeItem(row):
        itemAsJson = convertModelToJSON(row)
        # redis.hset(itemAsJson['id'], json.dumps(itemAsJson))
        redis.hset(f"{row.id}", mapping=itemAsJson)
        # redis.set(f'{row.id}', itemAsJson)
        return row

    def envelopeSequence(scalars):
        for item in scalars:
            yield envelopeItem(item)

    async def resultedFunction(session, skip, limit) -> Union[DBModel, None]:
        """Předkonfigurovaný dotaz bez filtru"""
        stmtWithFilter = stmt.offset(skip).limit(limit)

        dbSet = await session.execute(stmtWithFilter)
        result = dbSet.scalars()
        return envelopeSequence(result)

    return resultedFunction


def createEntityGetter(
    DBModel: BaseModel, options=None
) -> Callable[[AsyncSession, int, int], Awaitable[Union[BaseModel, None]]]:
    """Předkonfiguruje dotaz do databáze na vektor entit

    Parameters
    ----------
    DBModel : BaseModel
        class representing SQLAlchlemy model - table where record will be found
    options : any
        possible to use joinedload from SQLAlchemy
        for extending the query (select with join)

    Returns
    -------
    Callable[[AsyncSession, int, int], Awaitable[DBModel]]
        asynchronous function for query into database
    """

    if options is None:
        stmt = select(DBModel)
    else:
        if isinstance(options, list):
            stmt = select(DBModel).options(*options)
        else:
            stmt = select(DBModel).options(options)

    async def resultedFunction(session, skip, limit) -> Union[DBModel, None]:
        """Předkonfigurovaný dotaz bez filtru"""
        stmtWithFilter = stmt.offset(skip).limit(limit)

        dbSet = await session.execute(stmtWithFilter)
        result = dbSet.scalars()
        return result

    return resultedFunction


# r = redis.Redis(host='redis', decode_responses=True)
def createEntityByIdGetterWR(
    DBModel: BaseModel, options=None, redis=None
) -> Callable[[AsyncSession, int, int], Awaitable[Union[BaseModel, None]]]:
    """Předkonfiguruje dotaz do databáze na entitu podle id

    Parameters
    ----------
    DBModel : BaseModel
        class representing SQLAlchlemy model - table where record will be found
    options : any
        possible to use joinedload from SQLAlchemy
        for extending the query (select with join)

    Returns
    -------
    Callable[[AsyncSession, int, int], Awaitable[DBModel]]
        asynchronous function for query into database
    """
    assert options is None, "options cannot be used"
    assert redis is not None, "redis must be defined"

    stmt = select(DBModel)

    mapper = sqlalchemy.inspect(DBModel)
    columnNames = dict(
        (item.columns[0].name, item.columns[0].type)
        for item in mapper.column_attrs
    )

    # print(columnNames)

    predefinedSerialisers = {
        sqlalchemy.Boolean: lambda value: f"{value}",
        sqlalchemy.String: lambda value: value,
        sqlalchemy.DateTime: lambda value: f"{value}",
        # sqlalchemy.dialects.postgresql.UUID(as_uuid=True): lambda value: f"{value}",
        uuid.UUID: lambda value: f"{value}",
        sqlalchemy.BigInteger: lambda value: value,
    }

    serialisers = {}
    for colName, colType in columnNames.items():
        serialisers[colName] = predefinedSerialisers.get(
            colType, lambda value: f"{value}"
        )

    def convertModelToJSON(model: DBModel):
        result = dict(
            (name, serialisers[name](getattr(model, name)))
            for name in columnNames.keys()
        )
        # result = json.dumps(result)
        # result= result.encode('ascii')
        return result

    def convertJSONToModel(jsonData):
        result = DBModel()
        for columnName, columnType in columnNames.items():
            setattr(
                columnName,
                serialisers[columnName](jsonData.get(columnName, None))
            )
        return result

    def envelopeItem(row):
        itemAsJson = convertModelToJSON(row)
        # redis.hset(itemAsJson['id'], json.dumps(itemAsJson))
        rowId = itemAsJson["id"]
        redis.hset(rowId, mapping=itemAsJson)
        redis.expire(rowId, 30)
        # redis.set(f'{row.id}', itemAsJson)
        return row

    async def resultedFunction(session, id) -> Union[DBModel, None]:
        """Předkonfigurovaný dotaz bez filtru"""

        if redis.exists(id):
            redisResult = redis.hgetall(id)

            return convertJSONToModel(redisResult)
        else:
            stmtWithFilter = stmt.filter_by(id=id)

            dbSet = await session.execute(stmtWithFilter)
            result = next(dbSet.scalars(), None)
            return envelopeItem(result)

    return resultedFunction


def createEntityByIdGetter(
    DBModel: BaseModel, options=None
) -> Callable[[AsyncSession, uuid.UUID], Awaitable[Union[BaseModel, None]]]:
    """Předkonfiguruje dotaz do databáze na entitu podle id

    Parameters
    ----------
    DBModel : BaseModel
        class representing SQLAlchlemy model - table where record will be found
    options : any
        possible to use joinedload from SQLAlchemy
        for extending the query (select with join)

    Returns
    -------
    Callable[[AsyncSession, uuid.UUID], Awaitable[DBModel]]
        asynchronous function for query into database
    """

    if options is None:
        stmt = select(DBModel)
    else:
        if isinstance(options, list):
            stmt = select(DBModel).options(*options)
        else:
            stmt = select(DBModel).options(options)

    async def resultedFunction(session, id) -> Union[DBModel, None]:
        """Předkonfigurovaný dotaz bez filtru"""
        stmtWithFilter = stmt.filter_by(id=id)

        dbSet = await session.execute(stmtWithFilter)
        result = next(dbSet.scalars(), None)
        return result

    return resultedFunction


def create1NGetter(
    ResultedDBModel: BaseModel, foreignKeyName, options=None, filters=None
) -> Callable[[AsyncSession, uuid.UUID], Awaitable[List[BaseModel]]]:
    """Vytvori resolver pro relaci 1:N (M:N)
       Dotazujeme se na cizi entitu,
       ktera obsahuje foreingKey s patricnou hodnotou
       Ocekavanym navratem je vektor hodnot

    Parameters
    ----------
    ResultedDBModel : BaseModel
        class representing a model (SQLAlchemy) for result
    foreignKeyName : str
        name of foreignkey used for filtering entities
    options : any
        parameters for options parameters, usually joinedload from SQLAlchemy
    filters : dict
        set of filters applied to query

    Returns
    -------
    Callable[[AsyncSession, uuid.UUID], Awaitable[List[BaseModel]]]
        asynchronous function representing the resolver
        for 1:N (or N:M) relations on particular entity
    """
    if options is None:
        stmt = select(ResultedDBModel)
    else:
        if isinstance(options, list):
            stmt = select(ResultedDBModel).options(*options)
        else:
            stmt = select(ResultedDBModel).options(options)

    if filters is not None:
        if isinstance(filters, list):
            stmt = stmt.filter(*filters)
        else:
            stmt = stmt.filter(filters)

    async def ExecuteAndGetList(session: AsyncSession, stmt):
        """ "Sdilena funkce pro resolvery"""
        dbSet = await session.execute(stmt)
        result = dbSet.scalars()
        return result

    async def resultedFunction(
        session: AsyncSession,
        id: uuid.UUID,
        skip: int = 0,
        limit: int = 100,
        filters=None,
    ) -> List[ResultedDBModel]:
        """Predkonfigurovany dotaz bez filtru

        Parameters
        ----------
        session : AsyncSession
            session for DB (taken from SQLAlchemy)
        id: uuid.UUID
            key value used for foreign key

        Returns
        -------
        List[ResultedDBModel]
            vector of entities (1:N or M:N)
        """
        stmtWithFilter = stmt
        if filters is not None:
            if isinstance(filters, list):
                stmtWithFilter = stmtWithFilter.filter(*filters)
            else:
                stmtWithFilter = stmtWithFilter.filter(filters)

        filterQuery = {foreignKeyName: id}
        stmtWithFilter = (
            stmtWithFilter.filter_by(**filterQuery).offset(skip).limit(limit)
        )
        return await ExecuteAndGetList(session, stmtWithFilter)

    async def resultedFunctionWithFilters(
        session: AsyncSession, id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> List[ResultedDBModel]:
        """Predkonfigurovany dotaz s filtrem

        Parameters
        ----------
        session : AsyncSession
            session for DB (taken from SQLAlchemy)
        id: uuid.UUID
            key value used for foreign key

        Returns
        -------
        List[ResultedDBModel]
            vector of entities (1:N or M:N)
        """
        filterQuery = {**filters, foreignKeyName: id}
        stmtWithFilter = (
            stmt.filter_by(**filterQuery).
            offset(skip).
            limit(limit)
        )
        return await ExecuteAndGetList(session, stmtWithFilter)

    # if filters is None:
    #     return resultedFunction
    # else:
    #     return resultedFunctionWithFilters
    return resultedFunction


def createUpdateResolver(
    DBModel: BaseModel, safe=False
) -> Callable[[AsyncSession, uuid.UUID, dict], Awaitable[BaseModel]]:
    """Create update asynchronous resolver for DBmodel (SQLAlchemy)

    Parameters
    ----------
    DBModel : BaseModel
        the model (SQLAlchemy) which table contains a record being updated

    Returns
    ----------
    Callable[[session, id, data], awaitable]
        async function for update
    """

    async def resolveUpdate(
        session: AsyncSession, id: uuid.UUID, data: dict, extraAttributes={}
    ) -> Awaitable[DBModel]:
        """Updates a record with id=id according give data

        Parameters
        ----------
        DBModel : BaseModel
            the model (SQLAlchemy) which table contains a record being updated
        session : AsyncSession
            asynchronous session object which allows the update
        data : class
            datastructure holding the data for the update

        Returns
        ----------
        DBModel
            datastructure with updated items
        """
        stmt = select(DBModel).filter_by(id=id)
        dbSet = await session.execute(stmt)
        dbRecord = dbSet.scalars().first()
        result = update(dbRecord, data, extraAttributes)
        await session.commit()
        return result

    async def resolveUpdateSafe(
        session: AsyncSession, id: uuid.UUID, data: dict, extraAttributes={}
    ) -> Awaitable[DBModel]:
        """Updates a record with id=id according give data

        Parameters
        ----------
        DBModel : BaseModel
            the model (SQLAlchemy) which table contains a record being updated
        session : AsyncSession
            asynchronous session object which allows the update
        data : class
            datastructure holding the data for the update

        Returns
        ----------
        DBModel
            datastructure with updated items
        """
        stmt = select(DBModel).filter_by(id=id)
        dbSet = await session.execute(stmt)
        dbRecord = dbSet.scalars().first()

        if dbRecord.lastchange == data.lastchange:
            data.lastchange = datetime.datetime.now()
            result = update(dbRecord, data, extraAttributes)
            await session.commit()
        else:
            # someone updated meanwhile, return currentRecord
            result = dbRecord

        return result

    return resolveUpdateSafe if safe else resolveUpdate


def createInsertResolver(
    DBModel: BaseModel,
) -> Callable[[AsyncSession, BaseModel, dict], Awaitable[BaseModel]]:
    """Create insert asynchronous resolver for DBmodel (SQLAlchemy)

    Parameters
    ----------
    DBModel : BaseModel
        the model (SQLAlchemy) which table contains a record being inserted

    Returns
    ----------
    Callable[[session, id, data], awaitable]
        async function for update
    """

    async def resolveInsert(
        session,
        data,
        extraAttributes={}
    ) -> Awaitable[DBModel]:
        """Inserts a new record into database with given data

        Parameters
        ----------
        session : AsyncSession
            asynchronous session object which allows the update
        data : class
            datastructure holding the data for the update, could be None
        extraAttributes : dict
            extra key-values to be set in the new record,
            they are prioritized thus they can ovewrite data
        Returns
        ----------
        DBModel
            datastructure saved in database
        """
        dbRecord = DBModel()
        result = await putSingleEntityToDb(
            session, update(dbRecord, data, extraAttributes)
        )
        await session.commit()
        return result

    return resolveInsert


def createDBResolvers(BaseModel):
    """
    create a structure of resolvers derived from SQLAlchemy BaseModel

    result.UserModel.name
    result.UserModel.groups(GroupGQLModel)
    """

    def createLambda(DBModel):
        return lambda self: DeriveGQLResolvers(DBModel)

    attrs = {}

    for DBModel in BaseModel.registry.mappers:
        cls = DBModel.class_
        attrs[DBModel.class_.__name__] = property(cache(createLambda(cls)))
    
    # attrs["authorizations"] = property(cache(lambda self: AuthorizationLoader()))
    DBResolvers = type('DBResolvers', (), attrs)   
    return DBResolvers()


def createGQLTypeResolver():
    resolvedType = None
    def resolver(info: strawberry.types.Info):
        nonlocal resolvedType
        if resolvedType:
            return resolvedType
        _GQLModel = info.return_type

        if (_GQLModel.__class__.__name__ == "StrawberryOptional"):
            _GQLModel = _GQLModel.of_type

        if (_GQLModel.__class__.__name__ == "StrawberryList"):
            _GQLModel = _GQLModel.of_type

        if (isinstance(_GQLModel, strawberry.LazyType)):
            _GQLModel = _GQLModel.resolve_type()

        resolvedType = _GQLModel
        return _GQLModel
    return resolver

def DeriveGQLResolvers(DBModel):
    
    # attrs = inspect(DBModel).attrs
    # attrs = inspect(DBModel).all_orm_descriptors
    attrs = {
        **dict(inspect(DBModel).all_orm_descriptors),
        **dict(inspect(DBModel).attrs)
    }
    # attrs = dict(inspect(DBModel).all_orm_descriptors) + dict(inspect(DBModel).attrs)
    
    # print("dir(inspect(DBModel))", dir(inspect(DBModel)))
    # print("attrs", dict(attrs))
    # print("attrs", dict(attrs))
    # print("dict(inspect(DBModel).all_orm_descriptors)", dict(inspect(DBModel).all_orm_descriptors))
    
    def AsItemResolver(name, GQLModel=None, WhereFilterModel = None):
        assert hasattr(DBModel, name), f"{DBModel} has not attribute {name}, resolver cannot be created"
        resolveReturnType = createGQLTypeResolver()
        attr = attrs[name]
        # print("name, attr", name, attr, type(attr))
        if isinstance(attr, ColumnProperty):
            
            expr = attr.expression
            python_type = expr.type.python_type
            name = expr.name
            def resolveattribute(self) -> Optional[python_type]:
                return getattr(self, name)
            return resolveattribute
        elif isinstance(attr, hybrid_property):
            assert False, "using hybrid_property {name} is not supported (see {DBModel})"
        else:
            # print("name, attr", name, attr)
            assert GQLModel is not None, f"missing target GQLModel for resolution attribute {name} of {DBModel}"
            fkeys = list(attr._calculated_foreign_keys)
            assert len(fkeys) == 1, f"too complicated relation {DBModel} -> {attr.entity.class_}"
            fkeyname = f"{attr.entity.class_.__tablename__}.{fkeys[0].name}"
            fkeyname = fkeys[0].name

            async def resolvescalar(self, info: strawberry.types.Info) -> Optional[GQLModel]:
                _GQLModel = resolveReturnType(info)
                fkeyvalue = getattr(self, fkeyname)
                return await _GQLModel.resolve_reference(info, id=fkeyvalue)

            if WhereFilterModel is None:
                async def resolvevector(self, info: strawberry.types.Info) -> List[GQLModel]:
                    _GQLModel = resolveReturnType(info)
                    loader = _GQLModel.getLoader(info)
                    params = {fkeyname: self.id}
                    rows = await loader.filter_by(**params)
                    # async def page(self, skip=0, limit=10, where=None, orderby=None, desc=None, extendedfilter=None):
                    return rows
            else:
                async def resolvevector(self, info: strawberry.types.Info,
                    skip: Optional[int] = 0, limit: Optional[int] = 10,
                    where: Optional[WhereFilterModel] = None,
                    orderby: Optional[str] = None,
                    desc: Optional[bool] = None
                ) -> List[GQLModel]:
                    _GQLModel = resolveReturnType(info)
                    loader = _GQLModel.getLoader(info)
                    params = {fkeyname: self.id}
                    wheredict = None if where is None else strawberry.asdict(where)
                    # async def page(self, skip=0, limit=10, where=None, orderby=None, desc=None, extendedfilter=None):
                    # print(f"call of page for {DBModel} with {params}, expecting List[{_GQLModel}]")
                    # print(f"where is {wheredict}")
                    rows = await loader.page(
                        skip=skip, limit=limit, where=wheredict, 
                        orderby=orderby, desc=desc, extendedfilter=params
                    )
                    return rows
                pass
            return resolvevector if attr.uselist else resolvescalar
    # return AsItemResolver
    
    # 👇 root resolver for queries by value of primary key (id)
    def ByIdResolver(self, GQLModel):
        resolveReturnType = createGQLTypeResolver()    
        async def id_resolver(self, info: strawberry.types.Info, id: uuid.UUID) -> Optional[GQLModel]:
            _GQLModel = resolveReturnType(info)
            return await _GQLModel.resolve_reference(info, id=id)
        return id_resolver
    
    # 👇 root resolver for queries returning a list of entities
    # if WhereFilterModel is not defined, just resolver without filter capability is returned
    def PageResolver(self, GQLModel, WhereFilterModel = None):
        resolveReturnType = createGQLTypeResolver()
        if WhereFilterModel is None:
            async def page_resolver(self, info: strawberry.types.Info,
                skip: Optional[int] = 0, limit: Optional[int] = 10
            ) -> List[GQLModel]:
                _GQLModel = resolveReturnType(info)
                loader = _GQLModel.getLoader(info)
                return await loader.page(skip=skip, limit=limit)
        else:
            async def page_resolver(self, info: strawberry.types.Info,
                skip: Optional[int] = 0, limit: Optional[int] = 10,
                where: Optional[WhereFilterModel] = None,
                orderby: Optional[str] = None,
                desc: Optional[bool] = None
            ) -> List[GQLModel]:
                _GQLModel = resolveReturnType(info)
                wheredict = None if where is None else strawberry.asdict(where)
                loader = _GQLModel.getLoader(info)
                # async def page(self, skip=0, limit=10, where=None, orderby=None, desc=None, extendedfilter=None):
                return await loader.page(where=wheredict, skip=skip, limit=limit, orderby=orderby, desc=desc)
            
        return page_resolver
        
    def createLambda(name):
        return lambda self, GQLModel=None, WhereFilterModel=None: AsItemResolver(name, GQLModel, WhereFilterModel)
    clsattrs = {name: createLambda(name) for name, attr in attrs.items()}
    # print("clsattrs", clsattrs)
    for name, attr in attrs.items():
        if isinstance(attr, Relationship): print(name, attr)
        if isinstance(attr, Relationship): continue
        clsattrs[name] = property(cache(clsattrs[name]))
        
    clsattrs["resolve_by_id"] = ByIdResolver
    clsattrs["resolve_page"] = PageResolver

    DBResolvers = type(f'{DBModel.__class__.__name__}Resolvers', (), clsattrs)   
    return DBResolvers()

sentinel = "ea3afa47-3fc4-4d50-8b76-65e3d54cce01"
async def encapsulateInsert(info, loader, entity, result):
    actinguser = getUserFromInfo(info)
    id = uuid.UUID(actinguser["id"])
    rbacobject = getattr(entity, "rbacobject", sentinel)
    if rbacobject != sentinel:
        if rbacobject is None:
            entity.rbacobject = id

    entity.createdby = id

    row = await loader.insert(entity)
    assert result.msg is not None, "result msg must be predefined (Operation Insert)"
    result.id = row.id
    return result

async def encapsulateUpdate(info, loader, entity, result):
    actinguser = getUserFromInfo(info)
    id = uuid.UUID(actinguser["id"])
    entity.changedby = id

    row = await loader.update(entity)
    result.id = entity.id if result.id is None else result.id 
    result.msg = "ok" if row is not None else "fail"
    return result

import sqlalchemy.exc

async def encapsulateDelete(info, loader, id, result):
    # try:
    #     await loader.delete(id)
    # except sqlalchemy.exc.IntegrityError as e:
    #     result.msg='fail'
    # return result
    await loader.delete(id)
    return result

@classmethod
async def resolve_reference(cls, info: strawberry.types.Info, id: IDType):
    if id is None: return None
    if isinstance(id, str): id = IDType(id)
    loader = cls.getLoader(info)
    result = await loader.load(id)
    if result is not None:
        # result._type_definition = cls._type_definition  # little hack :)
        result.__strawberry_definition__ = cls.__strawberry_definition__  # little hack :)
    return result


import strawberry
import uuid
from typing import List, Optional
from sqlalchemy import inspect
from sqlalchemy.orm import ColumnProperty
from functools import cache

def createGQLTypeResolver():
    resolvedType = None
    def resolver(info: strawberry.types.Info):
        nonlocal resolvedType
        if resolvedType:
            return resolvedType
        _GQLModel = info.return_type

        if (_GQLModel.__class__.__name__ == "StrawberryOptional"):
            _GQLModel = _GQLModel.of_type

        if (_GQLModel.__class__.__name__ == "StrawberryList"):
            _GQLModel = _GQLModel.of_type

        if (isinstance(_GQLModel, strawberry.LazyType)):
            _GQLModel = _GQLModel.resolve_type()

        resolvedType = _GQLModel
        return _GQLModel
    return resolver

class DBResolver:
    def __init__(self, DBModel):
        self.DBModel = DBModel
        self.attrs = {
            **dict(inspect(DBModel).all_orm_descriptors),
            **dict(inspect(DBModel).attrs)
    }

    def ById(self, GQLModel):
        resolveReturnType = createGQLTypeResolver()    
        async def id_resolver(self, info: strawberry.types.Info, id: uuid.UUID) -> Optional[GQLModel]:
            _GQLModel = resolveReturnType(info)
            return await _GQLModel.resolve_reference(info, id=id)
        return id_resolver

    def Page(self, GQLModel, WhereFilterModel, skip=0, limit=10):
        resolveReturnType = createGQLTypeResolver()
        async def page_resolver(self, info: strawberry.types.Info,
            skip: Optional[int] = 0, limit: Optional[int] = 10,
            where: Optional[WhereFilterModel] = None,
            orderby: Optional[str] = None,
            desc: Optional[bool] = None
        ) -> List[GQLModel]:
            _GQLModel = resolveReturnType(info)
            wheredict = None if where is None else strawberry.asdict(where)
            loader = _GQLModel.getLoader(info)
            # async def page(self, skip=0, limit=10, where=None, orderby=None, desc=None, extendedfilter=None):
            return await loader.page(where=wheredict, skip=skip, limit=limit, orderby=orderby, desc=desc)
        return page_resolver
    
    def Attribute(self, name):
        assert hasattr(self.DBModel, name), f"{self.DBModel} has not attribute {name}, resolver cannot be created"
        # resolveReturnType = createGQLTypeResolver()
        attr = self.attrs[name]
        assert isinstance(attr, ColumnProperty), f"attribute {name} of model {self.DBModel} is not trivial"
            
        expr = attr.expression
        python_type = expr.type.python_type
        name = expr.name
        def resolveattribute(self) -> Optional[python_type]:
            return getattr(self, name)
        return resolveattribute

    # UNUSED
    # def Scalar(self, name, GQLModel):
    #     resolveReturnType = createGQLTypeResolver()
    #     attr = self.attrs[name]
    #     fkeys = list(attr._calculated_foreign_keys)
    #     assert len(fkeys) == 1, f"too complicated relation {self.DBModel} -> {attr.entity.class_}"
    #     fkeyname = f"{attr.entity.class_.__tablename__}.{fkeys[0].name}"
    #     fkeyname = fkeys[0].name

    #     async def resolvescalar(self, info: strawberry.types.Info) -> Optional[GQLModel]:
    #         _GQLModel = resolveReturnType(info)
    #         fkeyvalue = getattr(self, fkeyname)
    #         return await _GQLModel.resolve_reference(info, id=fkeyvalue)
    #         # return await GQLModel.resolve_reference(info, id=fkeyvalue)
    #     return resolvescalar

    def Vector(self, name, GQLModel, WhereFilterModel, skip=0, limit=10):
        resolveReturnType = createGQLTypeResolver()
        attr = self.attrs[name]
        fkeys = list(attr._calculated_foreign_keys)
        assert len(fkeys) == 1, f"too complicated relation {self.DBModel} -> {attr.entity.class_}"
        fkeyname = f"{attr.entity.class_.__tablename__}.{fkeys[0].name}"
        fkeyname = fkeys[0].name

        async def resolvevector(self, info: strawberry.types.Info,
            skip: Optional[int] = skip, limit: Optional[int] = limit,
            where: Optional[WhereFilterModel] = None,
            orderby: Optional[str] = None,
            desc: Optional[bool] = None
        ) -> List[GQLModel]:
            _GQLModel = resolveReturnType(info)
            loader = _GQLModel.getLoader(info)
            # loader = GQLModel.getLoader(info)
            params = {fkeyname: self.id}
            wheredict = None if where is None else strawberry.asdict(where)
            # async def page(self, skip=0, limit=10, where=None, orderby=None, desc=None, extendedfilter=None):
            # print(f"call of page for {DBModel} with {params}, expecting List[{_GQLModel}]")
            # print(f"where is {wheredict}")
            rows = await loader.page(
                skip=skip, limit=limit, where=wheredict, 
                orderby=orderby, desc=desc, extendedfilter=params
            )
            return rows
        return resolvevector
