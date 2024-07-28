import os
import functools
import requests
import aiohttp

import strawberry
import strawberry.types
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

fragmentRoleModel = """
fragment RoleModel on RoleGQLModel {
  __typename
  type: roletype {
    id
    name
    nameEn
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
"""
queryRBAC = """query RBAC($rbac_id: UUID!, $user_id: UUID) {
  rbacById(id: $rbac_id) {
    roles(userId: $user_id) {
      ...RoleModel
    }
  }
}
""" + fragmentRoleModel

queryMe = """query me {
  me {
    roles {
      ...RoleModel
    }
  }
}
""" + fragmentRoleModel

@strawberry.federation.type(extend=True, keys=["id"])
class RBACObjectGQLModel:
    id: IDType = strawberry.federation.field(external=True)
    
    @classmethod
    async def resolve_reference(cls, info: strawberry.types.Info, id: IDType):
        return None if id is None else cls(id=id)


    # @classmethod
    # async def resolve_roles(cls, info: strawberry.types.Info, id: IDType):
    #     loader = getLoadersFromInfo(info).authorizations
    #     authorizedroles = await loader.load(id)
    #     return authorizedroles

    
    @classmethod
    @functools.cache
    def getUrl(cls, url=None):
        _url = url
        if _url is None:
            _url = os.environ.get("GQLUG_ENDPOINT_URL", None)
            assert _url is not None
        return _url

    @classmethod
    def payload(cls):
        query = """query($limit: Int) {roleTypePage(limit: $limit) {id, name, nameEn}}"""
        variables = {"limit": 1000}

        json = {"query": query, "variables": variables}
        return json
   
    @classmethod
    @functools.cache
    def resolve_all_roles_sync(cls, url=None):
        _url = cls.getUrl(url=url)
        payload = cls.payload()
        response = requests.post(url=_url, json=payload)
        respText = response.text
        print("respText", respText, flush=True)
        respJson = response.json()
        print("respJson", respJson, flush=True)
        assert respJson.get("errors", None) is None, respJson["errors"]
        respdata = respJson.get("data", None)
        assert respdata is not None, f"during roles reading roles ('{_url}') have not been readed payload {payload}"
        [roles, *_] = respdata.values()
        assert roles is not None, f"during roles reading roles have not been readed payload {payload}"
        print("roles", roles)
        roles = list(map(lambda item: {"nameEn": item.get("name_en", None), **item, "name_en": item.get("nameEn", None)}, roles))
        return roles


    @classmethod
    async def resolve_all_roles_async(cls, info: strawberry.types.Info, url=None):
        client = cls.get_async_client(info=info)
        query = """query($limit: Int) {roles: roleTypePage(limit: $limit) {id, name, nameEn}}"""
        variables = {"limit": 1000}
        respJson = await client(query=query, variables=variables)
        assert respJson.get("errors", None) is None, respJson["errors"]
        respdata = respJson.get("data", None)
        assert respdata is not None, "during roles reading roles have not been readed"
        [roles, *_] = respdata.values()
        assert roles is not None, "during roles reading roles have not been readed"
        print("roles", roles)
        result = list(map(lambda item: {"nameEn": item.get("name_en", None), **item, "name_en": item.get("nameEn", None)}, roles))
        return result


    @classmethod
    async def resolve_all_roles(cls, info: strawberry.types.Info, url=None):
        # TODO rework to use async 
        # client = cls.get_async_client(info=info)
        # query = """query($limit: Int) {roles: roleTypePage(limit: $limit) {id, name, nameEn}}"""
        # variables = {"limit": 1000}
        # respJson = await client(query=query, variables=variables)
        # assert respJson.get("errors", None) is None, respJson["errors"]
        # respdata = respJson.get("data", None)
        # assert respdata is not None, "during roles reading roles have not been readed"
        # [roles, *_] = respdata.values()
        # assert roles is not None, "during roles reading roles have not been readed"
        # print("roles", roles)
        # roles = list(map(lambda item: {"nameEn": item.get("name_en", None), **item, "name_en": item.get("nameEn", None)}, roles))

        return cls.resolve_all_roles_sync()
        

    @classmethod
    def get_async_client(cls, info: strawberry.types.Info):
        _url = cls.getUrl()
        token = info.context["request"].scope["jwt"]
        cookies = {'authorization': token}        
        async def client(query, variables):
            payload = {"query": query, "variables": variables}
            async with aiohttp.ClientSession(cookies=cookies) as session:
                async with session.post(_url, json=payload) as resp:
                    assert resp.status == 200, f"bad status during query to resolve RBAC {resp}"
                    response = await resp.json()
                    return response
        return client

    @classmethod
    async def resolve_user_roles_on_object(cls, info: strawberry.types.Info, rbac_id: IDType, url=None):
        # _url = cls.getUrl(url=url)
        # token = info.context["request"].scope["jwt"]
        user = info.context["user"]
        rbac_index = user.get("rbac_index", None)
        if rbac_index is None:
            rbac_index = {}
            user["rbac_index"] = rbac_index
        user_roles = rbac_index.get(rbac_id, None)
        if user_roles is not None:
            return user_roles
        
        client = cls.get_async_client(info=info)
        
        variables = {
            "rbac_id": f"{rbac_id}",
            "user_id": f"{user['id']}"
        }
        response = await client(query=queryRBAC, variables=variables)
        assert "errors" not in response, f"got bad response {response}"
        [data, *_] = response.values()
        [rbac, *_] = data.values()
        [roles, *_] = rbac.values()
        rbac_index[rbac_id] = roles

        return roles

    @classmethod
    async def resolve_user_roles(cls, info: strawberry.types.Info):
        user = getUserFromInfo(info=info)
        user_roles = user.get("roles", None)
        if user_roles:
            return user_roles
        
        client = cls.get_async_client(info=info)
        
        response = await client(query=queryMe, variables={})
        assert "errors" not in response, f"got bad response {response}"
        [data, *_] = response.values()
        [me, *_] = data.values()
        [roles, *_] = me.values()
        user["roles"] = roles
        return roles

def CacheIt(async_function):
    cache = {"result": None}
    async def wrapped(self, info: strawberry.types.Info):
        result = cache.get("result", None)
        if result is None:
            result = await async_function(self, info)
            cache["result"] = result
        return result
    return wrapped
       
class WithRolesPermission(strawberry.BasePermission):   
    @classmethod
    @CacheIt
    async def RoleIndex(cls, info: strawberry.types.Info):
        allroles = await RBACObjectGQLModel.resolve_all_roles_async(info=info)
        result = {role["name"]: role["id"] for role in allroles}
        return result
    
    def __init__(self):
        super().__init__()
        self.roleIdsNeeded = None

    async def roleIdsNeeded(self, info, roleNames):
        if self.roleIdsNeeded is None:
            roleIndex = await WithRolesPermission.RoleIndex(info)
            roleIdsNeeded = list(map(lambda roleName: roleIndex[roleName], roleNames))
            self.roleIdsNeeded = roleIdsNeeded
        return self.roleIdsNeeded

# @functools.cache
# def RoleIndex():
#     allroles = RBACObjectGQLModel.resolve_all_roles_sync()
#     result = {role["name"]: role["id"] for role in allroles}
#     return result
    
sentinel = "ea3afa47-3fc4-4d50-8b76-65e3d54cce01"
@functools.cache
def RoleBasedPermission(roles: str = ""):
    "roles is string with delimiter ;"
    
    roleNames = roles.split(";")
    roleNames = list(map(lambda item: item.strip(), roleNames))

    class RolebasedPermission(WithRolesPermission):
        message = "User has not appropriate roles"
        def __init__(self):
            super().__init__()
            self.roleIdsNeeded = None

        def on_unauthorized(self) -> None:
            return self.defaultResult
        
        # async def roleIdsNeeded(self, info):
        #     if self.roleIdsNeeded is None:
        #         roleIndex = await WithRolesPermission.RoleIndex(info)
        #         roleIdsNeeded = list(map(lambda roleName: roleIndex[roleName], roleNames))
        #         self.roleIdsNeeded = roleIdsNeeded
        #     return self.roleIdsNeeded

        async def has_permission(
                self, source, info: strawberry.types.Info, **kwargs: dict
            # self, source, info: strawberry.types.Info, **kwargs
            # self, source, **kwargs
        ) -> bool:
            # print("RolebasedPermission kwargs", kwargs, flush=True)
            
            entity = source
            if entity is None:
                [entity, *_] = kwargs.values()
            assert entity is not None, f"missing source or param {kwargs}"
            self.defaultResult = [] if info._field.type.__class__ == StrawberryList else None
            rbacobject = getattr(entity, "rbacobject", sentinel)
            
            assert rbacobject != sentinel, f"type {type(entity)} has no attribute rbacobject"
            # return False
            authorizedroles = await RBACObjectGQLModel.resolve_user_roles_on_object(info=info, rbac_id=rbacobject)
            roleIdsNeeded = await self.roleIdsNeeded(info=info, roleNames=roleNames)
            allowedRoles = filter(lambda role: role["type"]["id"] in roleIdsNeeded, authorizedroles)
            isAllowed = next(allowedRoles, None)
            # logging.info(f"has_permission {kwargs}")
            # assert False
            # activeRoles = self.getActiveRoles(source, info)
            # isAllowed = await self.testIsAllowed(info, rbacobject=rbacobject, allowedRoleIds=roleIdsNeeded)
            # s = [r for r in activeRoles if (r["roletype"]["id"] in roleIdsNeeded)]           
            # isAllowed = len(s) > 0
            return isAllowed
        
    return RolebasedPermission

@functools.cache
def MustBeOneOfPermission(roles):
    roleNames = roles.split(";")
    roleNames = list(map(lambda item: item.strip(), roleNames))

    class OnlyForResultPermission(strawberry.BasePermission):

        def RoleIdsNeeded(self, roleIndex, roleNames):
            if self.roleIdsNeeded:
                return self.roleIdsNeeded
            self.roleIdsNeeded = list(map(lambda roleName: roleIndex[roleName], roleNames))
            return self.roleIdsNeeded

        message = f"User must play one role of '{roles}'"
        async def has_permission(self, source, info: strawberry.types.Info, **kwargs) -> bool:
            self.defaultResult = [] if info._field.type.__class__ == StrawberryList else None
            userRoles = await RBACObjectGQLModel.resolve_user_roles(info=info)
            roleIndex = await WithRolesPermission.RoleIndex(info=info)
            roleIdsNeeded = self.RoleIdsNeeded(roleIndex=roleIndex, roleNames=roleNames)
            appropriateRoles = filter(lambda role: role["type"]["id"] in roleIdsNeeded, userRoles)
            role = next(appropriateRoles, None)
            return (role is not None)
            
    return OnlyForResultPermission
