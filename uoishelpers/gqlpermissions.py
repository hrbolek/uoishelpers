import os
import functools
import requests
import aiohttp

import strawberry
from strawberry.types.base import StrawberryList
from functools import cached_property

from .resolvers import IDType, getLoadersFromInfo, getUserFromInfo

class OnlyForAuthentized(strawberry.permission.BasePermission):
    message = "User is not authenticated"

    async def has_permission(
        self, source, info: strawberry.types.Info, **kwargs
    ) -> bool:
        if self.isDEMO:
            # print("DEMO Enabled, not for production")
            return True
        
        self.defaultResult = [] if info._field.type.__class__ == StrawberryList else None
        user = getUserFromInfo(info)
        return (False if user is None else True)
    
    def on_unauthorized(self):
        return self.defaultResult
        
    @cached_property
    def isDEMO(self):
        DEMO = os.getenv("DEMO", None)
        return DEMO == "True"

@strawberry.federation.type(extend=True, keys=["id"])
class RBACObjectGQLModel:
    id: IDType = strawberry.federation.field(external=True)
    
    @classmethod
    async def resolve_reference(cls, info: strawberry.types.Info, id: IDType):
        return cls(id=id)


    @classmethod
    async def resolve_roles(cls, info: strawberry.types.Info, id: IDType):
        loader = getLoadersFromInfo(info).authorizations
        authorizedroles = await loader.load(id)
        return authorizedroles

    @classmethod
    @functools.cache
    def getUrl(cls, url=None):
        _url = url
        if _url is None:
            _url = os.environ.get("GQLUG_ENDPOINT_URL", None)
            assert _url is not None
        return _url

    @classmethod
    def payload():
        query = """query($limit: Int) {roles: roleTypePage(limit: $limit) {id, name, nameEn}}"""
        variables = {"limit": 1000}

        json = {"query": query, "variables": variables}
        return json
   
    @classmethod
    @functools.cache
    def resolve_all_roles_sync(cls, url=None):
        _url = cls.getUrl(url=url)
        payload = cls.payload()
        response = requests.post(url=_url, json=payload)
        respJson = response.json()

        assert respJson.get("errors", None) is None, respJson["errors"]
        respdata = respJson.get("data", None)
        assert respdata is not None, "during roles reading roles have not been readed"
        roles = respdata.get("roles", None)
        assert roles is not None, "during roles reading roles have not been readed"
        # print("roles", roles)
        roles = list(map(lambda item: {"nameEn": item["name_en"], **item, "name_en": item["nameEn"]}, roles))
        pass

    @classmethod
    async def resolve_all_roles(cls, info: strawberry.types.Info, url=None):
        # TODO rework to use async 
        return cls.resolve_all_roles_sync()
        
    @classmethod
    async def resolve_user_roles_on_object(cls, info: strawberry.types.Info, rbac_id: IDType, url=None):
        _url = cls.getUrl(url=url)
        token = info.context["request"].scope["jwt"]
        user = info.context["user"]
        cookies = {'authorization': token}
        query = """
query RBAC($rbac_id: UUID!, $user_id: UUID) {
  result: rbacById(id: $rbac_id) {
    roles(userId: $user_id) {
      __typename
      roletype {
        id
        name
      }
      group {
        id
        name
      }
      id
      valid
      startdate
      enddate
      user {
        id
        fullname
      }
    }
  }
}
"""
        variables = {
            "rbac_id": f"{rbac_id}",
            "user_id": f"{user['id']}"
        }
        payload = {"query": query, "variables": variables}
        async with aiohttp.ClientSession(cookies=cookies) as session:
            async with session.post(_url, json=payload) as resp:
                assert resp.status == 200, f"bad status during query to resolve RBAC {resp}"
                response = await resp.json()

        assert "errors" not in response, f"got bad response {response}"
        [data, *_] = response.values()
        [rbac, *_] = data.values()
        [roles, *_] = rbac.values()
        return roles
