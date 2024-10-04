from strawberry.extensions import SchemaExtension
from starlette.requests import Request
# import inspect
import aiohttp
import os
import asyncio

myquery = """
{
  me {
    id
    fullname
    email
    roles {
      valid
      group { id name }
      roletype { id name }
    }
  }
}"""

apolloQuery = "query __ApolloGetServiceDefinition__ { _service { sdl } }"
graphiQLQuery = "\n    query IntrospectionQuery {\n      __schema {\n        \n        queryType { name }\n        mutationType { name }\n        subscriptionType { name }\n        types {\n          ...FullType\n        }\n        directives {\n          name\n          description\n          \n          locations\n          args(includeDeprecated: true) {\n            ...InputValue\n          }\n        }\n      }\n    }\n\n    fragment FullType on __Type {\n      kind\n      name\n      description\n      \n      fields(includeDeprecated: true) {\n        name\n        description\n        args(includeDeprecated: true) {\n          ...InputValue\n        }\n        type {\n          ...TypeRef\n        }\n        isDeprecated\n        deprecationReason\n      }\n      inputFields(includeDeprecated: true) {\n        ...InputValue\n      }\n      interfaces {\n        ...TypeRef\n      }\n      enumValues(includeDeprecated: true) {\n        name\n        description\n        isDeprecated\n        deprecationReason\n      }\n      possibleTypes {\n        ...TypeRef\n      }\n    }\n\n    fragment InputValue on __InputValue {\n      name\n      description\n      type { ...TypeRef }\n      defaultValue\n      isDeprecated\n      deprecationReason\n    }\n\n    fragment TypeRef on __Type {\n      kind\n      name\n      ofType {\n        kind\n        name\n        ofType {\n          kind\n          name\n          ofType {\n            kind\n            name\n            ofType {\n              kind\n              name\n              ofType {\n                kind\n                name\n                ofType {\n                  kind\n                  name\n                  ofType {\n                    kind\n                    name\n                  }\n                }\n              }\n            }\n          }\n        }\n      }\n    }\n  "

class WhoAmIExtension(SchemaExtension):

    def getJWT(self):
        request: Request = self.execution_context.context["request"]
        cookies = request.cookies
        headers = request.headers
        jwtsource = cookies.get("authorization", None)
        if jwtsource is None:
            jwtsource = headers.get("Authorization", None)
            if jwtsource is not None:
                [_, jwtsource] = jwtsource.split("Bearer ")
            else:
                #unathorized
                pass
        return jwtsource
    
    async def ug_query(self, query, variables={}):
        ug_end_point = getattr(type(self), "GQLUG_ENDPOINT_URL", None)
        if ug_end_point is None:
            ug_end_point = os.environ.get("GQLUG_ENDPOINT_URL", None)
            setattr(type(self), "GQLUG_ENDPOINT_URL", ug_end_point)
            assert ug_end_point is not None, "missing explicit configuration, 'GQLUG_ENDPOINT_URL'"

        token = self.getJWT()
        cookies = {'authorization': token}        
        # print(f"cookies {cookies}", flush=True)
        payload = {"query": query, "variables": variables}
        async with aiohttp.ClientSession(cookies=cookies) as session:
            async with session.post(ug_end_point, json=payload) as resp:
                responsetxt = await resp.text()
                assert resp.status == 200, f"{ug_end_point} bad status during query {query} \n{resp} / {responsetxt}"
                response = await resp.json()
                return response

    async def on_execute(self):
        query = self.execution_context.query
        if query not in [apolloQuery, graphiQLQuery]:
            whoami = await self.ug_query(query=myquery)
            whoami = whoami["data"]["me"]
            self.execution_context.context["user"] = whoami
        else:
            whoami = {}

        # print("->on_execute", self.execution_context.query, flush=True)
        yield
        # print("on_execute->", whoami, flush=True)


