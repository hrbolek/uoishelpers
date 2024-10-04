
import os
from pydantic import BaseModel
import logging
from fastapi.responses import JSONResponse
from fastapi import FastAPI, Request
from strawberry.fastapi import GraphQLRouter

from .authenticationMiddleware import createAuthentizationSentinel


# region Sentinel setup
JWTPUBLICKEYURL = os.environ.get("JWTPUBLICKEYURL", "http://localhost:8000/oauth/publickey")
JWTRESOLVEUSERPATHURL = os.environ.get("JWTRESOLVEUSERPATHURL", "http://localhost:8000/oauth/userinfo")

apolloQuery = "query __ApolloGetServiceDefinition__ { _service { sdl } }"
graphiQLQuery = "\n    query IntrospectionQuery {\n      __schema {\n        \n        queryType { name }\n        mutationType { name }\n        subscriptionType { name }\n        types {\n          ...FullType\n        }\n        directives {\n          name\n          description\n          \n          locations\n          args(includeDeprecated: true) {\n            ...InputValue\n          }\n        }\n      }\n    }\n\n    fragment FullType on __Type {\n      kind\n      name\n      description\n      \n      fields(includeDeprecated: true) {\n        name\n        description\n        args(includeDeprecated: true) {\n          ...InputValue\n        }\n        type {\n          ...TypeRef\n        }\n        isDeprecated\n        deprecationReason\n      }\n      inputFields(includeDeprecated: true) {\n        ...InputValue\n      }\n      interfaces {\n        ...TypeRef\n      }\n      enumValues(includeDeprecated: true) {\n        name\n        description\n        isDeprecated\n        deprecationReason\n      }\n      possibleTypes {\n        ...TypeRef\n      }\n    }\n\n    fragment InputValue on __InputValue {\n      name\n      description\n      type { ...TypeRef }\n      defaultValue\n      isDeprecated\n      deprecationReason\n    }\n\n    fragment TypeRef on __Type {\n      kind\n      name\n      ofType {\n        kind\n        name\n        ofType {\n          kind\n          name\n          ofType {\n            kind\n            name\n            ofType {\n              kind\n              name\n              ofType {\n                kind\n                name\n                ofType {\n                  kind\n                  name\n                  ofType {\n                    kind\n                    name\n                  }\n                }\n              }\n            }\n          }\n        }\n      }\n    }\n  "


defaultSentinel = createAuthentizationSentinel(
    JWTPUBLICKEY=JWTPUBLICKEYURL,
    JWTRESOLVEUSERPATH=JWTRESOLVEUSERPATHURL,
    queriesWOAuthentization=[apolloQuery, graphiQLQuery],
    onAuthenticationError=lambda item: JSONResponse({"data": None, "errors": ["Unauthenticated", item.query, f"{item.variables}"]}, 
    status_code=401))

class Item(BaseModel):
    query: str
    variables: dict = {}
    operationName: str = None


def MountGuardedGQL(app, mountpoint="/gql", schema=None, get_context=None, DEMO="False", sentinel=defaultSentinel):
    assert schema is not None
    assert get_context is not None
    graphql_app = GraphQLRouter(
        schema,
        context_getter=get_context
    )

    @app.get(mountpoint)
    async def graphiql(request: Request):
        return await graphql_app.render_graphql_ide(request)

    async def serveGQLRequest(request, item):
        try:
            context = await get_context(request)
            context["user"] = request.scope.get("user", None)
            schemaresult = await schema.execute(query=item.query, variable_values=item.variables, operation_name=item.operationName, context_value=context)
        except Exception as e:
            logging.info(f"error during schema execute {e}")
            return {"data": None, "errors": [{"msg": f"{e}"}]}
        # logging.info(f"schema execute result \n{schemaresult}")
        result = {"data": schemaresult.data}
        if schemaresult.errors:
            result["errors"] = [
                {
                    "msg": error.message,
                    "locations": error.locations,
                    "path": error.path,
                    "nodes": error.nodes,
                    "source": error.source,
                    "original_error": { "type": f"{type(error.original_error)}", "msg": f"{error.original_error}" },
                    # "msg_r": f"{error}",
                    "msg_e": f"{error}".split('\n')
                } for error in schemaresult.errors]
        return result

    if DEMO in ["False", "false"]:
        @app.post(mountpoint)
        async def apollo_gql(request: Request, item: Item):

            sentinelResult = await sentinel(request, item)
            if sentinelResult:
                logging.info(f"sentinel test failed for query={item} \n request={request}")
                print(f"sentinel test failed for query={item} \n request={request}")
                return sentinelResult
            logging.info(f"sentinel test passed for query={item} for user {request.scope.get('user', None)}")
            return await serveGQLRequest(request, item)
            
    else:
        @app.post(mountpoint)
        async def apollo_gql(request: Request, item: Item):
            sentinelResult = await sentinel(request, item)
            if request.scope.get("user", None) is None:
                request.scope["user"] = {"id": "2d9dc5ca-a4a2-11ed-b9df-0242ac120003"}
            logging.info(f"sentinel skippend because of DEMO mode for query={item} for user {request.scope['user']}")
            return await serveGQLRequest(request, item)

    pass