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

        async def insert(self, entity):
            newdbrow = dbModel()
            newdbrow = update(newdbrow, entity)
            async with asyncSessionMaker() as session:
                session.add(newdbrow)
                await session.commit()
                self.clear(entity.id)
                self.prime(entity.id, entity)
                return entity

        async def update(self, entity, extraValues={}):
            dochecks = hasattr(entity, 'lastchange')               
            rowToUpdate = await self.load(entity.id)
            #print('loaded', rowToUpdate.id, rowToUpdate.name)
            if (dochecks and (entity.lastchange != rowToUpdate.lastchange)):
                result = None
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

        def registerResult(self, result):
            self.clear(result.id)
            self.prime(result.id, result)
            return result

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

    