from sqlalchemy.future import select

# async def recursiveSave(asyncSessionMaker, DBModels, dataTree):
#     """
#     """
    


#     pass

# async def recursiveSaveList(asyncSessionMaker, DBModels, listName, dataList):
#     DBModel = DBModels[listName]

#     reducedItems = []
#     for item in dataList:
#         newItem = {}
#         for key, value in item.items():
#             if type(value) is dict:
#                 continue
#             if type(value) is list:
#                 continue
#             newItem[key] = value
#         reducedItems.append(newItem)
    
#     putPredefinedStructuresIntoTable(asyncSessionMaker, DBModel, lambda : reducedItems)

#     for item in dataList:
#         for key, value in item.items():
#             if type(value) is dict:
#                 continue
#             if type(value) is list:
#                 recursiveSaveList(asyncSessionMaker, DBModels, key, value)

#     pass

async def putPredefinedStructuresIntoTable(asyncSessionMaker, DBModel, structureFunction):
    """Zabezpeci prvotni inicicalizaci zaznamu v databazi
       DBModel zprostredkovava tabulku,
       structureFunction() dava data, ktera maji byt ulozena, predpoklada se list of dicts, pricemz dict obsahuje elementarni datove typy
    """

    tableName = DBModel.__tablename__
    # column names
    cols = [col.name for col in DBModel.metadata.tables[tableName].columns]

    def mapToCols(item):
        """z item vybere jen atributy, ktere jsou v DBModel, zbytek je ignorovan"""
        result = {}
        for col in cols:
            value = item.get(col, None)
            if value is None:
                continue
            result[col] = value
        return result

    # ocekavane typy 
    externalIdTypes = structureFunction()
    
    #dotaz do databaze
    stmt = select(DBModel)
    async with asyncSessionMaker() as session:
        dbSet = await session.execute(stmt)
        dbRows = list(dbSet.scalars())
    
    #extrakce dat z vysledku dotazu
    #vezmeme si jen atribut id, id je typu uuid, tak jej zkovertujeme na string
    idsInDatabase = [f'{row.id}' for row in dbRows]

    # zjistime, ktera id nejsou v databazi
    unsavedRows = list(filter(lambda row: not(f'{row["id"]}' in idsInDatabase), externalIdTypes))
    
    # pro vsechna neulozena id vytvorime entity
    # omezime se jen na atributy, ktere jsou definovane v modelu
    mappedUnsavedRows = list(map(mapToCols, unsavedRows))
    rowsToAdd = [DBModel(**row) for row in mappedUnsavedRows]

    # a vytvorene entity jednou operaci vlozime do databaze
    async with asyncSessionMaker() as session:
        async with session.begin():
            session.add_all(rowsToAdd)
        await session.commit()

    # jeste jednou se dotazeme do databaze
    stmt = select(DBModel)
    async with asyncSessionMaker() as session:
        dbSet = await session.execute(stmt)
        dbRows = dbSet.scalars()
    
    #extrakce dat z vysledku dotazu
    idsInDatabase = [f'{row.id}' for row in dbRows]

    # znovu zaznamy, ktere dosud ulozeny nejsou, mely by byt ulozeny vsechny, takze prazdny list
    unsavedRows = list(filter(lambda row: not(f'{row["id"]}' in idsInDatabase), externalIdTypes))

    # ted by melo byt pole prazdne
    if not(len(unsavedRows) == 0):
        print('SOMETHING is REALLY WRONG')

    #print(structureFunction(), 'On the input')
    #print(dbRowsDicts, 'Defined in database')
    # nyni vsechny entity mame v pameti a v databazi synchronizovane
    #print(structureFunction())
    pass

async def ExportModels(sessionMaker, DBModels):
    """returns a dict of lists of dict
        it is a dict of tables (list) containing a rows (dict)
        DBModels defines a list of models to export
    """
    def ToDict(dbRow, cols):
        "Converts a row (sqlalchemy model) into dict"
        result = {}
        for col in cols:
            result[col] = getattr(dbRow, col)
        return result

    result = {}
    for DBModel in DBModels: # iterate over all models
        tableName = DBModel.__tablename__
        cols = [col.name for col in DBModel.metadata.tables[tableName].columns]
    
        # query for all items in a table
        stm = select(DBModel)
        async with sessionMaker() as session:
            dbRows = await session.execute(stm)
            dbData = dbRows.scalars()

        # convert all rows into list of dicts and insert it as a new key-value pair into result
        result[tableName] = [ToDict(row, cols) for row in dbData]
    return result

async def ImportModels(sessionMaker, DBModels, jsonData):
    """imports all data from json structure
        DBModels contains a list of sqlalchemy models
        jsonData data to import
    """

    # create index of all models, key is a table name, value is a model (sqlalchemy model)
    modelIndex = dict((DBModel.__tablename__, DBModel) for DBModel in DBModels)

    for tableName, DBModel in modelIndex.items(): # iterate over all models
        # get the appropriate data
        listData = jsonData.get(tableName, None)
        if listData is None:
            # data does not exists for current model
            continue
        # save data - all rows into a table, if a row with same id exists, do not save it nor update it
        await putPredefinedStructuresIntoTable(sessionMaker, DBModel, lambda: listData)