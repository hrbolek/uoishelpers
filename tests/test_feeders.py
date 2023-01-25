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

@pytest.mark.asyncio
async def test_import_json():
    [async_session_maker, UserModel, *_] = await prepare_in_memory_sqllite()

    data = {
        'users':[
            {'id': '1', 'name': 'John', 'surname': 'Newbie', 'email': 'john.newbie@world.com'},
            {'id': '2', 'name': 'Julia', 'surname': 'Newbie', 'email': 'julia.newbie@world.com'},
            {'id': '3', 'name': 'Johnson', 'surname': 'Newbie', 'email': 'johnson.newbie@world.com'},
            {'id': '4', 'name': 'Jepeto', 'surname': 'Newbie', 'email': 'jepeto.newbie@world.com'},
        ]
    }

    from uoishelpers.feeders import ImportModels

    await ImportModels(async_session_maker, [UserModel], data)

    stmt = sqlalchemy.select(UserModel)
    async with async_session_maker() as session:
        response = await session.execute(stmt)
        rows = list(response.scalars())
        print(rows)

        
    data = list(data.values())[0]
    result = [{'id': u.id, 'name': u.name, 'surname': u.surname, 'email': u.email} for u in rows]
    for dr, rr in zip(data, result):
        assert dr == rr

@pytest.mark.asyncio
async def test_import_json_chunks():
    [async_session_maker, UserModel, *_] = await prepare_in_memory_sqllite()

    data = {
        'users':[
            {'_chunk': 0, 'id': '1', 'name': 'John', 'surname': 'Newbie', 'email': 'john.newbie@world.com'},
            {'_chunk': 0, 'id': '2', 'name': 'Julia', 'surname': 'Newbie', 'email': 'julia.newbie@world.com'},
            {'_chunk': 1, 'id': '3', 'name': 'Johnson', 'surname': 'Newbie', 'email': 'johnson.newbie@world.com'},
            {'_chunk': 1, 'id': '4', 'name': 'Jepeto', 'surname': 'Newbie', 'email': 'jepeto.newbie@world.com'},
        ]
    }

    from uoishelpers.feeders import ImportModels

    await ImportModels(async_session_maker, [UserModel], data)

    stmt = sqlalchemy.select(UserModel)
    async with async_session_maker() as session:
        response = await session.execute(stmt)
        rows = list(response.scalars())
        print(rows)

        
    data = data['users']
    for d in data:
        del d['_chunk']
        
    result = [{'id': u.id, 'name': u.name, 'surname': u.surname, 'email': u.email} for u in rows]
    for dr, rr in zip(data, result):
        assert dr == rr


@pytest.mark.asyncio
async def test_import_json_missing_atribute():
    [async_session_maker, UserModel, *_] = await prepare_in_memory_sqllite()

    data = {
        'users':[
            {'id': '1', 'surname': 'Newbie', 'email': 'john.newbie@world.com'},
            {'id': '2', 'surname': 'Newbie', 'email': 'julia.newbie@world.com'},
            {'id': '3', 'surname': 'Newbie', 'email': 'johnson.newbie@world.com'},
            {'id': '4', 'surname': 'Newbie', 'email': 'jepeto.newbie@world.com'},
        ]
    }

    from uoishelpers.feeders import ImportModels

    await ImportModels(async_session_maker, [UserModel], data)

    stmt = sqlalchemy.select(UserModel)
    async with async_session_maker() as session:
        response = await session.execute(stmt)
        rows = list(response.scalars())
        print(rows)

        
    data = data['users']

    result = [{'id': u.id, 'surname': u.surname, 'email': u.email} for u in rows]
    for dr, rr in zip(data, result):
        assert dr == rr

@pytest.mark.asyncio
async def test_import_json_missing_table():
    [async_session_maker, UserModel, *_] = await prepare_in_memory_sqllite()

    data = {
        'groups':[
            {'id': '1', 'email': 'g1@world.com'},
            {'id': '2', 'email': 'g2@world.com'},
            {'id': '3', 'email': 'g3@world.com'},
            {'id': '4', 'email': 'g4@world.com'},
        ]
    }

    from uoishelpers.feeders import ImportModels

    await ImportModels(async_session_maker, [UserModel], data)

    stmt = sqlalchemy.select(UserModel)
    async with async_session_maker() as session:
        response = await session.execute(stmt)
        rows = list(response.scalars())

    assert len(rows) == 0

@pytest.mark.asyncio
async def test_export_json():
    [async_session_maker, UserModel, *_] = await prepare_in_memory_sqllite()

    data = {
        'users':[
            {'id': '1', 'name': 'John', 'surname': 'Newbie', 'email': 'john.newbie@world.com'},
            {'id': '2', 'name': 'Julia', 'surname': 'Newbie', 'email': 'julia.newbie@world.com'},
            {'id': '3', 'name': 'Johnson', 'surname': 'Newbie', 'email': 'johnson.newbie@world.com'},
            {'id': '4', 'name': 'Jepeto', 'surname': 'Newbie', 'email': 'jepeto.newbie@world.com'},
        ]
    }

    from uoishelpers.feeders import ImportModels, ExportModels

    await ImportModels(async_session_maker, [UserModel], data)

    result =  await ExportModels(async_session_maker, [UserModel])
    assert 'users' in result

    data = list(data.values())[0]
    result = result['users']
    #result = [{'id': u.id, 'name': u.name, 'surname': u.surname, 'email': u.email} for u in result]
    for dr, rr in zip(data, result):
        assert dr == rr


