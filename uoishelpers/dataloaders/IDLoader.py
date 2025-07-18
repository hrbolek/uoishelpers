import functools
import uuid
from typing import TypeVar, Generic, Type, Dict, Awaitable
from aiodataloader import DataLoader

from sqlalchemy import select, delete

import datetime
from dataclasses import fields, is_dataclass
import strawberry

def update(destination, source=None, extraValues={}, UNSET=strawberry.UNSET):
    """Updates destination's attributes with source's attributes.
    Attributes with value None are not updated."""
    if source is not None:
        # Vezmi pouze fieldy deklarované jako dataclass attribute
        for field in fields(destination):
            name = field.name
            value = getattr(source, name, None)
            if value is not UNSET:
                setattr(destination, name, value)
    for name, value in extraValues.items():
        setattr(destination, name, value)
    return destination


T = TypeVar("T")

class IDLoader(DataLoader[uuid.UUID, T], Generic[T]):
    dbModel: Type[T] = None

    @classmethod
    @functools.cache
    def __class_getitem__(cls, item):
        # Vrací novou podtřídu s přednastaveným .model
        name = f"{cls.__name__}[{item.__name__}]"
        return type(
            name,
            (cls,),
            {"dbModel": item}
        )
        
    @classmethod
    @functools.cache
    def createFkeySpecificLoader(cls, fkey: str, session=None):
        """Vytvoří novou podtřídu IDLoader s přednastaveným fkey."""
        result = FKeyLoader[cls.dbModel](session=session, foreignKeyName=fkey)
        return result

    def __init__(self, session):
        super().__init__()
        self.session = session
        if not self.dbModel:
            raise ValueError("Model must be specified using IDLoader[Model]")
        print(f"IDLoader initialized for model: {self.dbModel.__name__}")

    async def batch_load_fn(self, keys):
        # print(f"Using IDLoader on model: {self.dbModel.__name__} with keys: {keys}", flush=True)
        stmt = select(self.dbModel).where(self.dbModel.id.in_(keys))
        res = await self.session.execute(stmt)
        scalars = res.scalars()
        data = {row.id: row for row in scalars}
        result = [data.get(i) for i in keys]
        # print(f"Using IDLoader on model: {self.dbModel.__name__} \n\twith keys: {keys} \n\tgot result: {result}", flush=True)
        return result
    
    async def insert(self, entity, extraAttributes={}):
        newdbrow = self.dbModel()
        newdbrow = update(newdbrow, entity, extraAttributes)
        self.session.add(newdbrow)
        # await self.session.commit()
        # session should be autocommitted to make the whole graphql transaction atomic
        return newdbrow

    async def update(self, entity, extraValues={}):
        session = self.session
        result = None

        rowToUpdate = await session.get(self.dbModel, entity.id)
        if rowToUpdate is None:
            return None

        # Optimistic locking: kontrola lastchange
        if hasattr(rowToUpdate, 'lastchange'):
            if getattr(entity, 'lastchange', None) != rowToUpdate.lastchange:
                return None  # nebo raise Conflict
            # Nastav novou hodnotu lastchange (na rowToUpdate!)
            import datetime
            rowToUpdate.lastchange = datetime.datetime.now()

        # Aktualizuj hodnoty (pouze not-None fields, jak chceš)
        update(rowToUpdate, entity, extraValues)

        # NEVOLAT commit!
        self.registerResult(rowToUpdate)
        return rowToUpdate
    
    async def delete(self, id):
        stmt = delete(self.dbModel).where(self.dbModel.id == id)
        await self.session.execute(stmt)
        self.clear(id)
        # commit nevolat zde!

    def registerResult(self, result) -> T:
        self.clear(result.id)
        self.prime(result.id, result)
        return result
    
    async def execute_select(self, statement):
        #print(statement)
        rows = await self.session.execute(statement)
        return (
            self.registerResult(row)
            for row in rows.scalars()
        )    
    
    async def filter_by(self, **filters):
        if len(filters) == 1:
            cls = type(self)
            
            for key, value in filters.items():
                break
            fkeyloader = cls.createFkeySpecificLoader(fkey=key, session=self.session)
            results = await fkeyloader.load(value)
            registeredresults = (self.registerResult(result) for result in results)
            return registeredresults
        else:
            statement = select(self.dbModel).filter_by(**filters)
            return await self.execute_select(statement)        

    async def page(self, skip=0, limit=10, where=None, orderby=None, desc=None, extendedfilter=None):
        if where is not None:
            statement = prepareSelect(self.dbModel, where, extendedfilter)
        elif extendedfilter is not None:
            statement = select(self.dbModel).filter_by(**extendedfilter)
        else:
            statement = select(self.dbModel)
        statement = statement.offset(skip).limit(limit)
        # if extendedfilter is not None:
        #     statement = statement.filter_by(**extendedfilter)
        if orderby is not None:
            column = getattr(self.dbModel, orderby, None)
            if column is not None:
                if desc:
                    statement = statement.order_by(column.desc())
                else:
                    statement = statement.order_by(column.asc())

        return await self.execute_select(statement)

    def getModel(self):
        """Vrací model, pro který je tento IDLoader určen."""
        return self.dbModel
    
    def getSelectStatement(self):
        """Vrací SQLAlchemy select statement pro tento model."""
        return select(self.dbModel)
    
class FKeyLoader(DataLoader, Generic[T]):
    dbModel: Type[T] = None
    fkey: str = None

    @classmethod
    @functools.cache
    def __class_getitem__(cls, item):
        # Vrací novou podtřídu s přednastaveným .model
        name = f"{cls.__name__}[{item.__name__}]"
        return type(
            name,
            (cls,),
            {"dbModel": item}
        )
        
    def __init__(self, session, foreignKeyName):
        super().__init__()
        self.session = session
        self.foreignKeyName = foreignKeyName
        self.foreignKeyNameAttribute = getattr(self.dbModel, foreignKeyName)
        if not self.dbModel:
            raise ValueError("Model must be specified using FKeyLoader[Model]")
        print(f"FKeyLoader initialized for model: {self.dbModel.__name__} with foreign key {foreignKeyName}")

    async def batch_load_fn(self, keys):
        _keys = [*keys]
        #print('batch_load_fn', keys, flush=True)
        session = self.session
        
        statement = (
            select(self.dbModel)
            .order_by(self.foreignKeyNameAttribute)
            .filter(self.foreignKeyNameAttribute.in_(_keys))
        )
        rows = await session.execute(statement)
        rows = rows.scalars()
        # rows = list(rows)
        groupedResults = dict((key, [])  for key in _keys)
        for row in rows:
            #print(row)
            foreignKeyValue = getattr(row, self.foreignKeyName)
            groupedResult = groupedResults.get(foreignKeyValue, None)
            if groupedResult is None:
                groupedResult = []
                groupedResults[self.foreignKeyName] = groupedResult
            groupedResult.append(row)
            
        #print(groupedResults)
        return (groupedResults[key] for key in _keys)
    

def prepareSelect(model, where: dict, extendedfilter=None):   
    usedTables = [model.__tablename__]
    from sqlalchemy import select, and_, or_
    baseStatement = select(model)
    if extendedfilter is not None:
        baseStatement = baseStatement.filter_by(**extendedfilter)

    # stmt = select(GroupTypeModel).join(GroupTypeModel.groups.property.target).filter(GroupTypeModel.groups.property.target.c.name == "22-5KB")
    # type(GroupTypeModel.groups.property) sqlalchemy.orm.relationships.RelationshipProperty
    # GroupTypeModel.groups.property.entity.class_
    def limitDict(input):
        if isinstance(input, list):
            return [limitDict(item) for item in input]
        if not isinstance(input, dict):
            # print("limitDict", input)
            return input
        result = {key: limitDict(value) if isinstance(value, dict) else value for key, value in input.items() if value is not None}
        return result
    
    def convertAnd(model, name, listExpr):
        assert len(listExpr) > 0, "atleast one attribute in And expected"
        results = [convertAny(model, w) for w in listExpr]
        return and_(*results)

    def convertOr(model, name, listExpr):
        # print("enter convertOr", listExpr)
        assert len(listExpr) > 0, "atleast one attribute in Or expected"
        results = [convertAny(model, w) for w in listExpr]
        return or_(*results)

    def convertAttributeOp(model, name, op, value):
        # print("convertAttributeOp", type(model))
        # print("convertAttributeOp", model, name, op, value)
        column = getattr(model, name)
        assert column is not None, f"cannot map {name} to model {model.__tablename__}"
        opMethod = getattr(column, op)
        assert opMethod is not None, f"cannot map {op} to attribute {name} of model {model.__tablename__}"
        return opMethod(value)

    def convertRelationship(model, attributeName, where, opName, opValue):
        # print("convertRelationship", model, attributeName, where, opName, opValue)
        # GroupTypeModel.groups.property.entity.class_
        targetDBModel = getattr(model, attributeName).property.entity.class_
        # print("target", type(targetDBModel), targetDBModel)

        nonlocal baseStatement
        if targetDBModel.__tablename__ not in usedTables:
            baseStatement = baseStatement.join(targetDBModel)
            usedTables.append(targetDBModel.__tablename__)
        #return convertAttribute(targetDBModel, attributeName, opValue)
        return convertAny(targetDBModel, opValue)
        
        # stmt = select(GroupTypeModel).join(GroupTypeModel.groups.property.target).filter(GroupTypeModel.groups.property.target.c.name == "22-5KB")
        # type(GroupTypeModel.groups.property) sqlalchemy.orm.relationships.RelationshipProperty

    def convertAttribute(model, attributeName, where):
        woNone = limitDict(where)
        #print("convertAttribute", model, attributeName, woNone)
        keys = list(woNone.keys())
        assert len(keys) == 1, "convertAttribute: only one attribute in where expected"
        opName = keys[0]
        opValue = woNone[opName]

        ops = {
            "_eq": "__eq__",
            "_lt": "__lt__",
            "_le": "__le__",
            "_gt": "__gt__",
            "_ge": "__ge__",
            "_in": "in_",
            "_like": "like",
            "_ilike": "ilike",
            "_startswith": "startswith",
            "_endswith": "endswith",
        }

        opName = ops.get(opName, None)
        # if opName is None:
        #     print("op", attributeName, opName, opValue)
        #     result = convertRelationship(model, attributeName, woNone, opName, opValue)
        # else:
        result = convertAttributeOp(model, attributeName, opName, opValue)
        return result
        
    def convertAny(model, where):
        
        woNone = limitDict(where)
        # print("convertAny", woNone, flush=True)
        keys = list(woNone.keys())
        # print(keys, flush=True)
        # print(woNone, flush=True)
        assert len(keys) == 1, "convertAny: only one attribute in where expected"
        key = keys[0]
        value = woNone[key]
        
        convertors = {
            "_and": convertAnd,
            "_or": convertOr
        }
        #print("calling", key, "convertor", value, flush=True)
        #print("value is", value, flush=True)
        convertor = convertors.get(key, convertAttribute)
        convertor = convertors.get(key, None)
        modelAttribute = getattr(model, key, None)
        if (convertor is None) and (modelAttribute is None):
            assert False, f"cannot recognize {model}.{key} on {woNone}"
        if (modelAttribute is not None):
            property = getattr(modelAttribute, "property", None)
            target = getattr(property, "target", None)
            # print("modelAttribute", modelAttribute, target)
            if target is None:
                result = convertAttribute(model, key, value)
            else:
                result = convertRelationship(model, key, where, key, value)
        else:
            result = convertor(model, key, value)
        return result
    
    filterStatement = convertAny(model, limitDict(where))
    result = baseStatement.filter(filterStatement)
    return result

