from sqlalchemy import (
    Column,
    String,
)

from sqlalchemy.dialects.postgresql import UUID
import uuid

# def UUIDColumn(name=None):
#     if name is None:
#         return Column(
#               UUID(as_uuid=True),
#               primary_key=True,
#               server_default=sqlalchemy.text("gen_random_uuid()"),
#               unique=True,
#               index=True)
#     else:
#         return Column(
#               name,
#               UUID(as_uuid=True),
#               primary_key=True,
#               server_default=sqlalchemy.text("gen_random_uuid()"),
#               unique=True,
#               index=True)


def UUIDColumn(name=None, postgres=True):
    extraparams = {
        "primary_key": True,
        "unique": True,
        "index": True,
        "default": lambda: f"{uuid.uuid4()}",
    }
    columtype = String()
    if postgres: columtype = UUID(as_uuid=True)
        # columtype = UUID(as_uuid=False)
        # extraparams['server_default'] = sqlalchemy.text("gen_random_uuid()")
        # del extraparams['default']

    if name is None:
        return Column(columtype, **extraparams)
    else:
        return Column(name, columtype, **extraparams)