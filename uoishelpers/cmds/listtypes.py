import asyncio
import argparse
import pathlib
import aiohttp
import graphql


sdlquery = "{ _service { sdl }}"
async def getsld(port):
    sdl = ""
    async with aiohttp.ClientSession() as session:
        payload = {"query": sdlquery}
        async with session.post(f'http://localhost:{port}/gql', json=payload) as response:
            sdl = await response.json()
            assert "data" in sdl, "Response does not contain 'data' key"
            assert "errors" not in sdl, "Response contains errors"
            sdl_txt = sdl.get("data", {}).get("_service", {}).get("sdl", "")
            with open("schema.graphql", "w", encoding="utf-8") as f:
                f.write(sdl_txt)
    print(f"SDL: {sdl_txt}")
    return sdl_txt

from .utils_sdl_2 import (
    get_read_scalar_values, 
    get_cruds, 
    build_query_scalar, 
    GraphQLQueryBuilder, 
    explain_graphql_query,
    build_expanded_mutation
    )

def listtypes():
    parser = argparse.ArgumentParser()
    parser.add_argument('--foo')
    parser.add_argument('--schema', default="schema.graphql", help="Path to the schema file")
    args, unknown = parser.parse_known_args()
    print("Known args:", args)
    print("schema:", args.schema)
    print("Unknown raw args:", unknown)

    path = pathlib.Path(args.schema).resolve()
    print(f"Schema path: {path}")
    print("Hello from my command line tool! 2")
    sdl = asyncio.run(getsld(port=8000))
    directive_text = "directive @key(fields: String!) on OBJECT | INTERFACE"
    sdl = f"{directive_text}\n{sdl}"
    
    builder = GraphQLQueryBuilder(sdlfilename=f"{path}")
    ast = graphql.parse(sdl)
    r = get_cruds(ast)
    print(f"cruds: {r}")
    print("*"*30)
    for t, ops in r.items():    
        for op_type, special_ops in ops.items():
            print("*"*30)
            print(f"optype: {op_type}, type: {t}, special_ops: {special_ops}")
            # if op_type not in ["read", "readp"]:
            #     continue
            for op in special_ops:
                path = pathlib.Path(f"tests/queries/{t}/{op}.graphql").resolve()
                query = None
                print(f"Processing type: {t}, operation: {op}")
                if op_type == "read":
                    # query = builder.build_query_scalar(op, [t, "UserGQLModel"])
                    # query = builder.build_query_scalar(op, [t, "UserGQLModel"])
                    query = builder.build_query_scalar(op, [t])
                    # query = builder.build_query_scalar([t])
                    print(f"Query for {op}: {query}")
                if op_type == "readp":
                    # query = builder.build_query_vector(op, [t])
                    # query = builder.build_query_vector(op, [t, "UserGQLModel"])
                    query = builder.build_query_vector(op, [t])
                if op_type in ["insert", "update", "delete"]:
                    # query = builder.build_query_vector(op, [t])
                    # query = builder.build_query_vector(op, [t, "UserGQLModel"])
                    query = build_expanded_mutation(ast, op)
                if query is None:
                    print(f"Query for {op} not found, skipping...")
                    continue
                # read_query = build_query_scalar(ast, op)
                if query:
                    query = explain_graphql_query(ast, query)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    # print(f"read_query for {op}: {query}\nPath: {path}")
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(query)
        # break
    # print(f"Read scalar values: {r}")

    # print(f"Response: {response[:1000]}")