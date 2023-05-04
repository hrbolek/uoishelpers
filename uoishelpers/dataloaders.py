import datetime

from aiodataloader import DataLoader
from uoishelpers.resolvers import select, update

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

        def registerResult(self, result):
            self.clear(result.id)
            self.prime(result.id, result)
            return result

        def getSelectStatement(self):
            return select(dbModel)
        
        async def execute_select(self, statement):
            async with asyncSessionMaker() as session:
                rows = await session.execute(statement)
                return (
                    self.registerResult(row)
                    for row in rows.scalars()
                )
            
        async def filter_by(self, **filters):
            statement = mainstmt.filter_by(**filters)
            async with asyncSessionMaker() as session:
                rows = await session.execute(statement)
                return (
                    self.registerResult(row)
                    for row in rows.scalars()
                )

        async def page(self, skip=0, limit=10):
            statement = mainstmt.offset(skip).limit(limit)
            async with asyncSessionMaker() as session:
                rows = await session.execute(statement)
                return (
                    self.registerResult(row)
                    for row in rows.scalars()
                )
            
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

    