import asyncio
from aiodataloader import DataLoader
from collections import defaultdict

from strawberry.extensions import SchemaExtension

from graphql import parse, print_ast, OperationType
from graphql.language.ast import (
    FieldNode,
    NameNode,
    ArgumentNode,
    IntValueNode,
    StringValueNode,
    SelectionSetNode,
    OperationDefinitionNode,
    DocumentNode,
)

def build_batch_query_with_ast(base_query_str, ids):
    base_ast = parse(base_query_str)
    base_op = base_ast.definitions[0]
    field = base_op.selection_set.selections[0]

    aliased_fields = []
    for i, id_value in enumerate(ids, start=1):
        alias_name = f"item{i}"

        # Úprava argumentů
        new_arguments = []
        for arg in field.arguments:
            if arg.name.value == "id":
                new_arguments.append(
                    ArgumentNode(
                        name=NameNode(value="id"),
                        value=StringValueNode(value=str(id_value))
                    )
                )
            else:
                new_arguments.append(arg)

        new_field = FieldNode(
            alias=NameNode(value=alias_name),
            name=field.name,
            arguments=new_arguments,
            selection_set=field.selection_set
        )
        aliased_fields.append(new_field)

    # ⏹️ Odstraníme $id z variable_definitions (pokud tam je)
    new_variable_definitions = [
        v for v in base_op.variable_definitions or []
        if v.variable.name.value != "id"
    ]

    new_op = OperationDefinitionNode(
        operation=OperationType.QUERY,
        name=base_op.name,
        variable_definitions=new_variable_definitions or None,
        selection_set=SelectionSetNode(selections=aliased_fields)
    )

    doc = DocumentNode(definitions=[new_op])
    return print_ast(doc)


def extract_values_from_batch_result(result):
    """
    Extrahuje hodnoty z aliasovaných odpovědí GraphQL batch dotazu.

    :param result: dict s klíčem "data" obsahujícím aliasované odpovědi
    :return: seznam hodnot ve stejném pořadí jako aliasy (item1, item2, ...)
    """
    data = result.get("data", {})
    print(f"extract_values_from_batch_result.data = {data}", flush=True)
    # Seřadíme aliasy podle pořadí: item1, item2, ...
    ordered_items = sorted(
        ((k, v) for k, v in data.items() if k.startswith("item")),
        key=lambda kv: int(kv[0][4:])  # extrahuje číslo z "itemN"
    )
    return [v for _, v in ordered_items]

class GraphQLBatchLoader(DataLoader):
    def __init__(self, gqlClient, base_query_str):
        super().__init__()
        self.gqlClient = gqlClient
        self.base_query_str = base_query_str

    def load(self, key):
        frozenkey = frozenset(key.items())
        return super().load(frozenkey)
    
    async def batch_load_fn(self, keys):
        # 1. Rozdělení na skupiny podle parametrů mimo "id"
        groups = defaultdict(list)
        for index, key in enumerate(keys):
            restored_key = dict(key)
            # print(f"restored_key= {restored_key}")
            context = frozenset((k, v) for k, v in restored_key.items() if k != "id")
            groups[context].append((index, restored_key["id"]))

        # 2. Vytvoření všech futures pro jednotlivé skupiny
        tasks = []
        group_keys = []

        for context, index_id_pairs in groups.items():
            ids = [id_ for _, id_ in index_id_pairs]
            variables = dict(context)

            task = self._fetch_batch(ids, variables)
            tasks.append(task)
            group_keys.append(index_id_pairs)

        # 3. Spuštění všech skupin paralelně
        batch_results = await asyncio.gather(*tasks)

        # 4. Naplnění výsledků ve správném pořadí
        results = [None] * len(keys)
        for index_id_pairs, group_items in zip(group_keys, batch_results):
            for (orig_index, _), item in zip(index_id_pairs, group_items):
                results[orig_index] = item

        return results

    async def _fetch_batch(self, ids, variables):
        query = build_batch_query_with_ast(self.base_query_str, ids)
        result = await self.gqlClient(query=query, variables=variables)
        return extract_values_from_batch_result(result)


TestNoStateAccessQuery = """query TestNoStateAccess($id: UUID! $user_id: UUID!, $roles: [String!]!) {
  rbacById(id: $id) {
    result: userCanWithoutState(userId: $user_id, rolesNeeded: $roles)
  }
}"""

TestStateAccessQuery = """query TestStateAccess($id: UUID! $user_id: UUID!, $state_id: UUID!, $access: StateDataAccessType!) {
  rbacById(id: $id) {
    result: userCanWithState(userId: $user_id, access: $access, stateId: $state_id)
  }
}"""

GetUserRolesForRBACQuery = """query GetUserRolesForRBACQuery($id: UUID! $user_id: UUID!) {
  rbacById(id: $id) {
    result: roles(userId: $user_id) {
      roletype {
        __typename
        id
        name
        path
        subtypes {
          __typename
          id
          name
          path
        }
      }
      userId
      valid
      startdate
      enddate
      group {
        grouptype {
          id
          name
        }
        id
        name
      }
    }
  }
}"""

class RolePermissionSchemaExtension(SchemaExtension):

    async def on_execute(self):
        context = self.execution_context
        gqlClient = context.context.get("ug_client", None)
        # assert gqlClient is not None, "ug_client must be provided in context"
        loader = GraphQLBatchLoader(gqlClient, TestNoStateAccessQuery)
        context.context["userCanWithoutState_loader"] = loader
        loader = GraphQLBatchLoader(gqlClient, TestStateAccessQuery)
        context.context["userCanWithState_loader"] = loader
        loader = GraphQLBatchLoader(gqlClient, GetUserRolesForRBACQuery)
        context.context["userRolesForRBACQuery_loader"] = loader

        # keyA = {"user_id": "51d101a0-81f1-44ca-8366-6cf51432e8d6", "id": "7533c953-e88b-48a2-a41c-b61631395247", "roles": ("administrátor", )}
        # keyB = {"user_id": "51d101a0-81f1-44ca-8366-6cf51432e8d6", "id": "8191cee1-8dba-4a2a-b9af-3f986eb0b51a", "roles": ("administrátor", )}
        # contextA = frozenset(keyA.items())
        # contextB = frozenset(keyB.items())

        # queries = [
        #     loader.load(contextA),
        #     loader.load(contextB)
        # ]
        # results = await asyncio.gather(*queries)
        # print(f"ExperimentExtension results: {results}")
        yield None

