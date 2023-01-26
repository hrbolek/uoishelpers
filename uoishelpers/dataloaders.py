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
                return (rows.scalars())

        async def insert(self, entity):
            async with asyncSessionMaker() as session:
                session.add(entity)
                await session.commit()
                self.clear(entity.id)
                self.prime(entity.id, entity)
                return entity

        async def update(self, entity, extraValues={}):
            dochecks = hasattr(entity, 'lastchange')               
            rowToUpdate = await self.load(entity.id)
            #print('loaded', rowToUpdate.id, rowToUpdate.name)
            if (dochecks and (entity.lastchange != rowToUpdate.lastchange)):
                result = rowToUpdate
            else:
                if dochecks:
                    entity.lastchange = datetime.datetime.now()

                async with asyncSessionMaker() as session:
                    rowToUpdate = update(rowToUpdate, entity, extraValues=extraValues)
                    #print('updated', rowToUpdate.id, rowToUpdate.name)
                    await session.commit()
                    #print('after commit', rowToUpdate.id, rowToUpdate.name)
                    result = rowToUpdate
                    self.clear(result.id)
                    self.prime(result.id, result)
                    #self.clear_all()

            return result

        async def execute_select(self, statement):
            def registerResult(result):
                self.clear(result.id)
                self.prime(result.id, result)
                return result

            async with asyncSessionMaker() as session:
                rows = await session.execute(statement)
                return (
                    registerResult(row)
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
    filtermethod = dbModel.id.in_
    class Loader(DataLoader):
        async def batch_load_fn(self, keys):
            #print('batch_load_fn', keys, flush=True)
            async with asyncSessionMaker() as session:
                statement = mainstmt.filter(filtermethod(keys))
                rows = await session.execute(statement)
                rows = rows.scalars()
                groupedResults = dict((key, [])  for key in keys)
                for row in rows:
                    foreignKeyValue = getattr(row, foreignKeyName)
                    groupedResult = groupedResults[foreignKeyValue]
                    groupedResult.append(row)
                return (groupedResults.values())   
    return Loader(cache=True)

    