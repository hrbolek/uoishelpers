import datetime
import logging

from aiodataloader import DataLoader
from uoishelpers.resolvers import select, update, delete


def prepareSelect(model, where: dict):   
    from sqlalchemy import select, and_, or_
    baseStatement = select(model)

    def limitDict(input):
        result = {key: value for key, value in input.items() if value is not None}
        return result
    
    def convertAnd(name, listExpr):
        assert len(listExpr) > 0, "atleast one attribute in And expected"
        results = [convertAny(w) for w in listExpr]
        return and_(*results)

    def convertOr(name, listExpr):
        #print("enter convertOr", listExpr)
        assert len(listExpr) > 0, "atleast one attribute in Or expected"
        results = [convertAny(w) for w in listExpr]
        return or_(*results)

    def convertAttributeOp(name, op, value):
        column = getattr(model, name)
        assert column is not None, f"cannot map {name} to model {model.__tablename__}"
        opMethod = getattr(column, op)
        assert opMethod is not None, f"cannot map {op} to attribute {name} of model {model.__tablename__}"
        return opMethod(value)

    def convertAttribute(attributeName, where):
        woNone = limitDict(where)
        #print("convertAttribute", attributeName, woNone)
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
        opName = ops[opName]
        #print("op", attributeName, opName, opValue)
        result = convertAttributeOp(attributeName, opName, opValue)
        return result
        
    def convertAny(where):
        
        woNone = limitDict(where)
        #print("convertAny", woNone, flush=True)
        keys = list(woNone.keys())
        #print(keys, flush=True)
        #print(woNone, flush=True)
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

        result = convertor(key, value)
        return result
    
    filterStatement = convertAny(where)
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
            print(statement)

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
            statement = mainstmt
            if where is not None:
                statement = prepareSelect(dbModel, where)
            statement = statement.offset(skip).limit(limit)
            if extendedfilter is not None:
                statement = statement.filter_by(**extendedfilter)
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