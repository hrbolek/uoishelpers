from sqlalchemy.future import select


async def putPredefinedStructuresIntoTable(
    asyncSessionMaker, DBModel, structureFunction
):
    """Zabezpeci prvotni inicicalizaci zaznamu v databazi
    DBModel zprostredkovava tabulku,
    structureFunction() dava data, ktera maji byt ulozena,
    predpoklada se list of dicts, pricemz dict obsahuje elementarni datove typy
    """
    #print("putPredefinedStructuresIntoTable")
    tableName = DBModel.__tablename__
    # column names
    cols = [col.name for col in DBModel.metadata.tables[tableName].columns]
    # print(cols)

    def mapToCols(item):
        """
        z item vybere jen atributy, ktere jsou v DBModel,
        zbytek je ignorovan"""
        result = {}
        for col in cols:
            value = item.get(col, None)
            if value is None:
                continue
            result[col] = value
        return result

    # ocekavane typy
    externalIdTypes = structureFunction()

    # dotaz do databaze
    stmt = select(DBModel)
    async with asyncSessionMaker() as session:
        dbSet = await session.execute(stmt)
        dbRows = list(dbSet.scalars())

    # extrakce dat z vysledku dotazu
    # vezmeme si jen atribut id,
    # id je typu uuid, tak jej zkovertujeme na string
    idsInDatabase = [f"{row.id}" for row in dbRows]

    #print('found in database', idsInDatabase)
    #print(dbRows[3].name)
    # zjistime, ktera id nejsou v databazi
    unsavedRows = list(
        filter(
            lambda row: not (f'{row["id"]}' in idsInDatabase),
            externalIdTypes
        )
    )

    async def saveChunk(rows):
        # pro vsechna neulozena id vytvorime entity
        # omezime se jen na atributy, ktere jsou definovane v modelu
        mappedUnsavedRows = list(map(mapToCols, rows))
        rowsToAdd = [DBModel(**row) for row in mappedUnsavedRows]

        # a vytvorene entity jednou operaci vlozime do databaze
        async with asyncSessionMaker() as session:
            async with session.begin():
                session.add_all(rowsToAdd)
            await session.commit()

    if len(unsavedRows) > 0:
        # je co ukladat
        if "_chunk" in unsavedRows[0]:
            # existuje informace o rozfazovani ukladani do tabulky
            nextPhase = [*unsavedRows]
            while len(nextPhase) > 0:
                # zjistime nejmensi cislo poradi ukladani
                chunkNumber = min(map(lambda item: item["_chunk"], nextPhase))
                # filtrujeme radky, ktere maji toto cislo
                toSave = list(
                    filter(
                        lambda item: item["_chunk"] == chunkNumber,
                        nextPhase
                    )
                )
                # ostatni nechame na pozdeji
                nextPhase = list(
                    filter(
                        lambda item: item["_chunk"] != chunkNumber,
                        nextPhase
                    )
                )
                # ulozime vybrane
                await saveChunk(toSave)
        else:
            # vsechny zaznamy mohou byt ulozeny soucasne, 
            # ukladame po blocich
            while (len(unsavedRows) > 0):
                rowsToSave = unsavedRows[:30]
                await saveChunk(rowsToSave)
                unsavedRows = unsavedRows[30:]

    # jeste jednou se dotazeme do databaze
    stmt = select(DBModel)
    async with asyncSessionMaker() as session:
        dbSet = await session.execute(stmt)
        dbRows = dbSet.scalars()

    # extrakce dat z vysledku dotazu
    idsInDatabase = [f"{row.id}" for row in dbRows]

    # znovu zaznamy, ktere dosud ulozeny nejsou,
    # mely by byt ulozeny vsechny, takze prazdny list
    unsavedRows = list(
        filter(
            lambda row: not (f'{row["id"]}' in idsInDatabase),
            externalIdTypes
        )
    )

    # ted by melo byt pole prazdne
    if not (len(unsavedRows) == 0): print("SOMETHING is REALLY WRONG")

    # print(structureFunction(), 'On the input')
    # print(dbRowsDicts, 'Defined in database')
    # nyni vsechny entity mame v pameti a v databazi synchronizovane
    # print(structureFunction())
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
    for DBModel in DBModels:  # iterate over all models
        tableName = DBModel.__tablename__
        cols = [col.name for col in DBModel.metadata.tables[tableName].columns]

        # query for all items in a table
        stm = select(DBModel)
        async with sessionMaker() as session:
            dbRows = await session.execute(stm)
            dbData = dbRows.scalars()

        # convert all rows into list of dicts and
        # insert it as a new key-value pair into result
        result[tableName] = [ToDict(row, cols) for row in dbData]
    return result


async def ImportModels(sessionMaker, DBModels, jsonData):
    """imports all data from json structure
    DBModels contains a list of sqlalchemy models
    jsonData data to import
    """

    # create index of all models,
    # key is a table name,
    # value is a model (sqlalchemy model)
    modelIndex = dict((DBModel.__tablename__, DBModel) for DBModel in DBModels)

    for tableName, DBModel in modelIndex.items():  # iterate over all models
        # get the appropriate data
        listData = jsonData.get(tableName, None)
        if listData is None:
            # data does not exists for current model
            continue
        # save data - all rows into a table,
        # if a row with same id exists, do not save it nor update it
        await putPredefinedStructuresIntoTable(
            sessionMaker, DBModel, lambda: listData
        )
