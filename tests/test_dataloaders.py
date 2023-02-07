import uuid
import sqlalchemy
import sys
import asyncio

# setting path
sys.path.append('../uoishelpers')

import pytest 
#from ..uoishelpers.uuid import UUIDColumn
import uoishelpers
async def prepare_in_memory_sqllite():
    from sqlalchemy import Column, String, BigInteger, Integer, DateTime, ForeignKey, Sequence, Table, Boolean
    from sqlalchemy.orm import declarative_base
    from uoishelpers.uuid import UUIDColumn

    BModel = declarative_base()

    class UserBM(BModel):
        __tablename__ = 'users'
        
        id = uoishelpers.uuid.UUIDColumn(postgres=False)
        name = Column(String)
        surname = Column(String)
        email = Column(String)

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    asyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:")
    #asyncEngine = create_async_engine("sqlite+aiosqlite:///data.sqlite")
    async with asyncEngine.begin() as conn:
        await conn.run_sync(BModel.metadata.create_all)    

    async_session_maker = sessionmaker(
        asyncEngine, expire_on_commit=False, class_=AsyncSession
    )

    return async_session_maker, UserBM

async def prepare_in_memory_sqllite_2():
    from sqlalchemy import Column, String, BigInteger, Integer, DateTime, ForeignKey, Sequence, Table, Boolean
    from sqlalchemy.orm import declarative_base
    from uoishelpers.uuid import UUIDColumn

    BModel = declarative_base()

    class UserBM(BModel):
        __tablename__ = 'users'
        
        id = uoishelpers.uuid.UUIDColumn(postgres=False)
        name = Column(String)
        surname = Column(String)
        email = Column(String)
        lastchange = Column(DateTime)

    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    asyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:")
    #asyncEngine = create_async_engine("sqlite+aiosqlite:///data.sqlite")
    async with asyncEngine.begin() as conn:
        await conn.run_sync(BModel.metadata.create_all)    

    async_session_maker = sessionmaker(
        asyncEngine, expire_on_commit=False, class_=AsyncSession
    )

    return async_session_maker, UserBM

@pytest.mark.asyncio
async def test_put_1():
    [async_session_maker, UserModel, *_] = await prepare_in_memory_sqllite()

    data = [
        {'id': '1', 'name': 'John', 'surname': 'Newbie', 'email': 'john.newbie@world.com'},
        {'id': '2', 'name': 'Julia', 'surname': 'Newbie', 'email': 'julia.newbie@world.com'},
        {'id': '3', 'name': 'Johnson', 'surname': 'Newbie', 'email': 'johnson.newbie@world.com'},
        {'id': '4', 'name': 'Jepeto', 'surname': 'Newbie', 'email': 'jepeto.newbie@world.com'},
    ]

    from uoishelpers.feeders import putPredefinedStructuresIntoTable

    await putPredefinedStructuresIntoTable(async_session_maker, UserModel, lambda:data)

    stmt = sqlalchemy.select(UserModel)
    async with async_session_maker() as session:
        response = await session.execute(stmt)
        rows = list(response.scalars())
        print(rows)

        
    result = [{'id': u.id, 'name': u.name, 'surname': u.surname, 'email': u.email} for u in rows]
    for dr, rr in zip(data, result):
        assert dr == rr



@pytest.mark.asyncio
async def test_loader_load_single():
    [async_session_maker, UserModel, *_] = await prepare_in_memory_sqllite()

    data = [
        {'id': '1', 'name': 'John', 'surname': 'Newbie', 'email': 'john.newbie@world.com'},
    ]

    from uoishelpers.feeders import putPredefinedStructuresIntoTable

    await putPredefinedStructuresIntoTable(async_session_maker, UserModel, lambda:data)

    from uoishelpers.dataloaders import createIdLoader

    userLoader = createIdLoader(async_session_maker, UserModel)
    u = await userLoader.load(key='1')

    assert data[0] == {'id': u.id, 'name': u.name, 'surname': u.surname, 'email': u.email}

@pytest.mark.asyncio
async def test_loader_load_multi():
    [async_session_maker, UserModel, *_] = await prepare_in_memory_sqllite()

    data = [
        {'id': '1', 'name': 'John', 'surname': 'Newbie', 'email': 'john.newbie@world.com'},
        {'id': '2', 'name': 'Julia', 'surname': 'Newbie', 'email': 'julia.newbie@world.com'},
        {'id': '3', 'name': 'Johnson', 'surname': 'Newbie', 'email': 'johnson.newbie@world.com'},
        {'id': '4', 'name': 'Jepeto', 'surname': 'Newbie', 'email': 'jepeto.newbie@world.com'},
    ]

    from uoishelpers.feeders import putPredefinedStructuresIntoTable

    await putPredefinedStructuresIntoTable(async_session_maker, UserModel, lambda:data)

    from uoishelpers.dataloaders import createIdLoader

    userLoader = createIdLoader(async_session_maker, UserModel)

    ids = [item['id'] for item in data]
    print(ids)
    loadings = (userLoader.load(key=id) for id in ids)
    rows = await asyncio.gather(*loadings)

    result = [{'id': u.id, 'name': u.name, 'surname': u.surname, 'email': u.email} for u in rows]
    for dr, rr in zip(data, result):
        assert dr == rr


@pytest.mark.asyncio
async def test_loader_load_multi_same():
    [async_session_maker, UserModel, *_] = await prepare_in_memory_sqllite()

    data = [
        {'id': '1', 'name': 'John', 'surname': 'Newbie', 'email': 'john.newbie@world.com'},
        {'id': '2', 'name': 'Julia', 'surname': 'Newbie', 'email': 'julia.newbie@world.com'},
        {'id': '3', 'name': 'Johnson', 'surname': 'Newbie', 'email': 'johnson.newbie@world.com'},
        {'id': '4', 'name': 'Jepeto', 'surname': 'Newbie', 'email': 'jepeto.newbie@world.com'},
    ]

    from uoishelpers.feeders import putPredefinedStructuresIntoTable

    await putPredefinedStructuresIntoTable(async_session_maker, UserModel, lambda:data)

    from uoishelpers.dataloaders import createIdLoader

    userLoader = createIdLoader(async_session_maker, UserModel)

    id0 = data[0]['id']
    ids = [id0 for item in data]
    ids.append('x')

    print(ids)
    loadings = (userLoader.load(key=id) for id in ids)
    rows = await asyncio.gather(*loadings)

    result = [{'id': u.id, 'name': u.name, 'surname': u.surname, 'email': u.email} if u is not None else None for u in rows]
    assert len(result) == len(data) + 1
    for r in result:
        if r is not None:
            assert r['id'] == id0
    assert r is None


@pytest.mark.asyncio
async def test_loader_execute_select():
    [async_session_maker, UserModel, *_] = await prepare_in_memory_sqllite()

    data = [
        {'id': '1', 'name': 'John', 'surname': 'Newbie', 'email': 'john.newbie@world.com'},
        {'id': '2', 'name': 'Julia', 'surname': 'Newbie', 'email': 'julia.newbie@world.com'},
        {'id': '3', 'name': 'Johnson', 'surname': 'Newbie', 'email': 'johnson.newbie@world.com'},
        {'id': '4', 'name': 'Jepeto', 'surname': 'Newbie', 'email': 'jepeto.newbie@world.com'},
    ]

    from uoishelpers.feeders import putPredefinedStructuresIntoTable

    await putPredefinedStructuresIntoTable(async_session_maker, UserModel, lambda:data)

    from uoishelpers.dataloaders import createIdLoader

    userLoader = createIdLoader(async_session_maker, UserModel)

    ids = [item['id'] for item in data]
    print(ids)

    from uoishelpers.feeders import select
    statement = select(UserModel)
    rows = await userLoader.execute_select(statement)
    rows = list(rows)
    result = [{'id': u.id, 'name': u.name, 'surname': u.surname, 'email': u.email} for u in rows]
    for dr, rr in zip(data, result):
        assert dr == rr

    loadings = (userLoader.load(key=id) for id in ids)
    rows = await asyncio.gather(*loadings)

    result = [{'id': u.id, 'name': u.name, 'surname': u.surname, 'email': u.email} for u in rows]
    for dr, rr in zip(data, result):
        assert dr == rr


@pytest.mark.asyncio
async def test_loader_update():
    [async_session_maker, UserModel, *_] = await prepare_in_memory_sqllite()

    data = [
        {'id': '1', 'name': 'John', 'surname': 'Newbie', 'email': 'john.newbie@world.com'},
        {'id': '2', 'name': 'Julia', 'surname': 'Newbie', 'email': 'julia.newbie@world.com'},
        {'id': '3', 'name': 'Johnson', 'surname': 'Newbie', 'email': 'johnson.newbie@world.com'},
        {'id': '4', 'name': 'Jepeto', 'surname': 'Newbie', 'email': 'jepeto.newbie@world.com'},
    ]

    from uoishelpers.feeders import putPredefinedStructuresIntoTable

    await putPredefinedStructuresIntoTable(async_session_maker, UserModel, lambda:data)

    from uoishelpers.dataloaders import createIdLoader

    userLoader = createIdLoader(async_session_maker, UserModel)

    ids = [item['id'] for item in data]

    newName = "Chandler"    
    item = await userLoader.update(UserModel(id=ids[-1], name=newName))

    loadings = (userLoader.load(key=id) for id in ids)
    rows = await asyncio.gather(*loadings)

    result = [{'id': u.id, 'name': u.name, 'surname': u.surname, 'email': u.email} for u in rows]
    #print('result[3]', result[3])

    assert data[0] == result[0]
    assert data[1] == result[1]
    assert data[2] == result[2]
    assert data[3] != result[3]

    assert result[3]['name'] == newName

import datetime

@pytest.mark.asyncio
async def test_loader_update_with_lastchange():
    [async_session_maker, UserModel, *_] = await prepare_in_memory_sqllite_2()

    data = [
        {'id': '1', 'name': 'John', 'surname': 'Newbie', 'email': 'john.newbie@world.com'},
        {'id': '2', 'name': 'Julia', 'surname': 'Newbie', 'email': 'julia.newbie@world.com'},
        {'id': '3', 'name': 'Johnson', 'surname': 'Newbie', 'email': 'johnson.newbie@world.com'},
        {'id': '4', 'name': 'Jepeto', 'surname': 'Newbie', 'email': 'jepeto.newbie@world.com'},
    ]

    now = datetime.datetime.now()
    for item in data:
        item['lastchange'] = now

    from uoishelpers.feeders import putPredefinedStructuresIntoTable

    await putPredefinedStructuresIntoTable(async_session_maker, UserModel, lambda:data)

    from uoishelpers.dataloaders import createIdLoader

    userLoader = createIdLoader(async_session_maker, UserModel)

    ids = [item['id'] for item in data]
    newName = 'Chandler'
    item = await userLoader.update(UserModel(id=ids[-1], name=newName, lastchange=now))
    assert item.name == newName
    assert item.lastchange != now

    newLastchange = item.lastchange
    newName = 'Chappie'
    item = await userLoader.update(UserModel(id=ids[-1], name=newName, lastchange=now))
    assert item.name != newName
    assert item.lastchange == newLastchange


@pytest.mark.asyncio
async def test_loader_insert():
    [async_session_maker, UserModel, *_] = await prepare_in_memory_sqllite()

    data = [
        {'id': '1', 'name': 'John', 'surname': 'Newbie', 'email': 'john.newbie@world.com'},
        {'id': '2', 'name': 'Julia', 'surname': 'Newbie', 'email': 'julia.newbie@world.com'},
        {'id': '3', 'name': 'Johnson', 'surname': 'Newbie', 'email': 'johnson.newbie@world.com'},
        {'id': '4', 'name': 'Jepeto', 'surname': 'Newbie', 'email': 'jepeto.newbie@world.com'},
    ]

    from uoishelpers.feeders import putPredefinedStructuresIntoTable

    await putPredefinedStructuresIntoTable(async_session_maker, UserModel, lambda:data)

    from uoishelpers.dataloaders import createIdLoader

    userLoader = createIdLoader(async_session_maker, UserModel)

    ids = [item['id'] for item in data]

    newId = '-1'
    newName = "Chandler"    
    await userLoader.insert(UserModel(id=newId, name=newName))

    ids.append(newId)
    loadings = (userLoader.load(key=id) for id in ids)
    rows = await asyncio.gather(*loadings)

    result = [{'id': u.id, 'name': u.name, 'surname': u.surname, 'email': u.email} for u in rows]
    #print('result[3]', result[3])

    assert data[0] == result[0]
    assert data[1] == result[1]
    assert data[2] == result[2]
    assert data[3] == result[3]

    assert len(result) == 5
    assert result[4]['name'] == newName
    assert result[4]['id'] == newId



@pytest.mark.asyncio
async def test_loader_external_cache():
    [async_session_maker, UserModel, *_] = await prepare_in_memory_sqllite()

    data = [
        {'id': '1', 'name': 'John', 'surname': 'Newbie', 'email': 'john.newbie@world.com'},
        {'id': '2', 'name': 'Julia', 'surname': 'Newbie', 'email': 'julia.newbie@world.com'},
        {'id': '3', 'name': 'Johnson', 'surname': 'Newbie', 'email': 'johnson.newbie@world.com'},
        {'id': '4', 'name': 'Jepeto', 'surname': 'Newbie', 'email': 'jepeto.newbie@world.com'},
    ]

    from uoishelpers.feeders import putPredefinedStructuresIntoTable

    await putPredefinedStructuresIntoTable(async_session_maker, UserModel, lambda:data)

    from uoishelpers.dataloaders import createIdLoader

    externalcache = {}
    userLoader = createIdLoader(async_session_maker, UserModel)
    userLoader.set_cache(externalcache)

    ids = [item['id'] for item in data]

    loadings = (userLoader.load(key=id) for id in ids)
    rows = await asyncio.gather(*loadings)

    rows = list(externalcache.values())
    rows = [row.result() for row in rows]

    result = [{'id': u.id, 'name': u.name, 'surname': u.surname, 'email': u.email} for u in rows]
    #print('result[3]', result[3])
    print(result)


    assert data[0] == result[0]
    assert data[1] == result[1]
    assert data[2] == result[2]
    assert data[3] == result[3]
