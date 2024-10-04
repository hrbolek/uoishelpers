import datetime
import logging
import uuid
import json

from aiodataloader import DataLoader
from uoishelpers.resolvers import select, update, delete


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

def createIdLoader(asyncSessionMaker, dbModel):

    mainstmt = select(dbModel)
    filtermethod = dbModel.id.in_
    class Loader(DataLoader):
        async def batch_load_fn(self, keys):
            #print('batch_load_fn', keys, flush=True)
            async with asyncSessionMaker() as session:
                statement = mainstmt.filter(filtermethod(keys))
                rows = await session.execute(statement)
                rows = rows.scalars()
                #return rows
                datamap = {}
                for row in rows:
                    datamap[row.id] = row
                result = [datamap.get(id, None) for id in keys]
                return result

        async def insert(self, entity, extraAttributes={}):
            newdbrow = dbModel()
            #print("insert", newdbrow, newdbrow.id, newdbrow.name, flush=True)
            newdbrow = update(newdbrow, entity, extraAttributes)
            async with asyncSessionMaker() as session:
                #print("insert", newdbrow, newdbrow.id, newdbrow.name, flush=True)
                session.add(newdbrow)
                await session.commit()
            #self.clear(newdbrow.id)
            #self.prime(newdbrow.id, newdbrow)
            #print("insert", newdbrow, newdbrow.id, newdbrow.name, flush=True)
            return newdbrow

        async def update(self, entity, extraValues={}):
            async with asyncSessionMaker() as session:
                statement = mainstmt.filter_by(id=entity.id)
                rows = await session.execute(statement)
                rows = rows.scalars()
                rowToUpdate = next(rows, None)

                if rowToUpdate is None:
                    return None

                dochecks = hasattr(rowToUpdate, 'lastchange')             
                checkpassed = True  
                #print('loaded', rowToUpdate)
                #print('loaded', rowToUpdate.id, rowToUpdate.name)
                if (dochecks):
                    #print('checking', flush=True)
                    if (entity.lastchange != rowToUpdate.lastchange):
                        #print('checking failed', flush=True)
                        result = None
                        checkpassed = False                        
                    else:
                        entity.lastchange = datetime.datetime.now()
                        #print(entity)           
                if checkpassed:
                    rowToUpdate = update(rowToUpdate, entity, extraValues=extraValues)
                    #print('updated', rowToUpdate.id, rowToUpdate.name, rowToUpdate.lastchange)
                    await session.commit()
                    #print('after commit', rowToUpdate.id, rowToUpdate.name, rowToUpdate.lastchange)
                    #print('after commit', row.id, row.name, row.lastchange)
                    result = rowToUpdate
                    self.registerResult(result)
                
                #self.clear_all()
            # cacherow = await self.load(result.id)
            # print("cacherow", cacherow, flush=True)
            # print("cacherow", cacherow.name, cacherow.id, flush=True)
            # print("cacherow", list(self._cache.keys()), flush=True)
            # cachevalue = await self._cache.get(entity.id)
            # print("cacherow", cachevalue.id, cachevalue.name, flush=True)
            return result

        async def delete(self, id):
            statement = delete(dbModel).where(dbModel.id==id)
            async with asyncSessionMaker() as session:
                result = await session.execute(statement)
                await session.commit()
                self.clear(id)
                return result

        def registerResult(self, result):
            self.clear(result.id)
            self.prime(result.id, result)
            return result

        def getSelectStatement(self):
            return select(dbModel)
        
        def getModel(self):
            return dbModel
        
        def getAsyncSessionMaker(self):
            return asyncSessionMaker
        
        async def execute_select(self, statement):
            #print(statement)

            async with asyncSessionMaker() as session:
                rows = await session.execute(statement)
                return (
                    self.registerResult(row)
                    for row in rows.scalars()
                )
            
        async def filter_by(self, **filters):
            statement = mainstmt.filter_by(**filters)
            logging.debug(f"loader is executing statement {statement}")
            return await self.execute_select(statement)

        async def page(self, skip=0, limit=10, where=None, orderby=None, desc=None, extendedfilter=None):
            if where is not None:
                statement = prepareSelect(dbModel, where, extendedfilter)
            elif extendedfilter is not None:
                statement = mainstmt.filter_by(**extendedfilter)
            else:
                statement = mainstmt
            statement = statement.offset(skip).limit(limit)
            # if extendedfilter is not None:
            #     statement = statement.filter_by(**extendedfilter)
            if orderby is not None:
                column = getattr(dbModel, orderby, None)
                if column is not None:
                    if desc:
                        statement = statement.order_by(column.desc())
                    else:
                        statement = statement.order_by(column.asc())

            return await self.execute_select(statement)
            
        def set_cache(self, cache_object):
            self.cache = True
            self._cache = cache_object


    return Loader(cache=True)

def createFkeyLoader(asyncSessionMaker, dbModel, foreignKeyName=None):
    assert foreignKeyName is not None, "foreignKeyName must be defined"
    foreignKeyNameAttribute = getattr(dbModel, foreignKeyName)
    mainstmt = select(dbModel).order_by(foreignKeyNameAttribute)
    fkeyattr = getattr(dbModel, foreignKeyName)
    filtermethod = fkeyattr.in_
    class Loader(DataLoader):
        async def batch_load_fn(self, keys):
            #print('batch_load_fn', keys, flush=True)
            async with asyncSessionMaker() as session:
                statement = mainstmt.filter(filtermethod(keys))
                rows = await session.execute(statement)
                rows = rows.scalars()
                rows = list(rows)
                groupedResults = dict((key, [])  for key in keys)
                for row in rows:
                    #print(row)
                    foreignKeyValue = getattr(row, foreignKeyName)
                    groupedResult = groupedResults[foreignKeyValue]
                    groupedResult.append(row)
                    
                #print(groupedResults)
                return (groupedResults.values())   
    return Loader(cache=True)

from functools import cache

async def createLoaders(asyncSessionMaker, models):
    def createLambda(loaderName, DBModel):
        return lambda self: createIdLoader(asyncSessionMaker, DBModel)
    
    attrs = {}
    for key, DBModel in models.items():
        attrs[key] = property(cache(createLambda(key, DBModel)))
    
    Loaders = type('Loaders', (), attrs)   
    return Loaders()   

def createLoadersAuto(asyncSessionMaker, BaseModel, extra={}):
    def createLambda(loaderName, DBModel):
        return lambda self: createIdLoader(asyncSessionMaker, DBModel)

    attrs = {}

    for DBModel in BaseModel.registry.mappers:
        cls = DBModel.class_
        attrs[cls.__tablename__] = property(cache(createLambda(asyncSessionMaker, cls)))
        attrs[cls.__name__] = attrs[cls.__tablename__]

    for key, value in extra.items():
        attrs[key] = property(cache(lambda self: value()))
    Loaders = type('Loaders', (), attrs)   
    return Loaders()

def readJsonFile(jsonFileName):
    def datetime_parser(json_dict):
        for (key, value) in json_dict.items():
            if key in ["startdate", "enddate", "lastchange", "created"]:
                if value is None:
                    dateValueWOtzinfo = None
                else:
                    try:
                        dateValue = datetime.datetime.fromisoformat(value)
                        dateValueWOtzinfo = dateValue.replace(tzinfo=None)
                    except:
                        print("jsonconvert Error", key, value, flush=True)
                        dateValueWOtzinfo = None
                
                json_dict[key] = dateValueWOtzinfo
            
            if (key in ["id", "changedby", "createdby", "rbacobject"]) or ("_id" in key):
                
                if key == "outer_id":
                    json_dict[key] = value
                elif value not in ["", None]:
                    json_dict[key] = uuid.UUID(value)
                else:
                    print(key, value)

        return json_dict

    with open(jsonFileName, "r", encoding="utf-8") as f:
        jsonData = json.load(f, object_hook=datetime_parser)

    return jsonData