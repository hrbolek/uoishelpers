import asyncio
import time
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

_MISSING = object()

class L1TTLCache(dict):
    """
    Lokální (per-process) TTL cache, kompatibilní s dict API pro aiodataloader cache_map.

    - žádný background task
    - expirace se kontroluje jen pro dotčený klíč
    - maxsize je jen pojistka; při přetečení smaže pár expirovaných, jinak pár libovolných
    """

    def __init__(self, ttl_seconds: float = 15.0, maxsize: int = 10_000):
        super().__init__()
        self.ttl = float(ttl_seconds)
        self.maxsize = int(maxsize)
        self._expires: dict[Any, float] = {}

    def _now(self) -> float:
        return time.monotonic()

    def _expired(self, key) -> bool:
        exp = self._expires.get(key)
        return exp is not None and exp <= self._now()

    def _purge_if_expired(self, key) -> bool:
        if self._expired(key):
            super().pop(key, None)
            self._expires.pop(key, None)
            return True
        return False

    def _maybe_evict(self):
        if len(self) <= self.maxsize:
            return

        # 1) zkus vyhodit expirované (rychle)
        now = self._now()
        for k in list(self._expires.keys()):
            if self._expires.get(k, now + 1) <= now:
                super().pop(k, None)
                self._expires.pop(k, None)
                if len(self) <= self.maxsize:
                    return

        # 2) když pořád přetečeno, smaž pár libovolných (pojistka)
        overflow = len(self) - self.maxsize
        if overflow > 0:
            for k in list(self.keys())[:overflow]:
                super().pop(k, None)
                self._expires.pop(k, None)

    # --- dict API ---
    def __contains__(self, key) -> bool:
        self._purge_if_expired(key)
        return super().__contains__(key)

    def get(self, key, default=None):
        self._purge_if_expired(key)
        return super().get(key, default)

    def __getitem__(self, key):
        if self._purge_if_expired(key):
            raise KeyError(key)
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._expires[key] = self._now() + self.ttl
        self._maybe_evict()

    def pop(self, key, default=_MISSING):
        self._expires.pop(key, None)
        if default is _MISSING:
            return super().pop(key)
        return super().pop(key, default)

    def clear(self):
        self._expires.clear()
        return super().clear()

def freeze(v):
    if isinstance(v, dict):
        return frozenset((k, freeze(val)) for k, val in v.items())
    if isinstance(v, (list, tuple, set)):
        return tuple(freeze(x) for x in v)
    return v

def freeze_key(d: dict):
    return frozenset((k, freeze(v)) for k, v in d.items())

class GraphQLBatchLoader(DataLoader):
    """
    Batchovací DataLoader pro GraphQL dotazy.

    Umožňuje efektivně načítat více objektů pomocí jednoho GraphQL dotazu.
    Místo opakovaných dotazů typu:

        query { item(id: "1") { ... } }
        query { item(id: "2") { ... } }
        query { item(id: "3") { ... } }

    vytvoří jeden batch dotaz s aliasy:

        query {
            item1: item(id: "1") { ... }
            item2: item(id: "2") { ... }
            item3: item(id: "3") { ... }
        }

    a po obdržení odpovědi výsledek opět rozdělí do správného pořadí.

    Hlavní vlastnosti:

    - `load(key)`:
        - `key` je slovník parametrů dotazu.
        - Aby byl hashovatelný, ukládá se jako `frozenset(key.items())`.

    - `batch_load_fn(keys)`:
        - klíče rozdělí do skupin podle všech parametrů *kromě id*,
          takže každý unikátní „kontext“ (např. {user_id: x}) vytvoří
          samostatný batch,
        - pro každou skupinu připraví seznam ID a spustí dotaz `_fetch_batch`,
        - výsledky vrátí ve stejném pořadí, v jakém byly volány `load()`.

    - `_fetch_batch(ids, variables)`:
        - postaví GraphQL dotaz s více aliasovanými fieldy
          pomocí `build_batch_query_with_ast(...)`,
        - pošle jej přes `gqlClient`,
        - extrahuje hodnoty aliasů ve správném pořadí pomocí
          `extract_values_from_batch_result(...)`.

    Použití:
    - Ideální pro RBAC dotazy, kdy chceme najednou zjistit role uživatele
      nad více objekty nebo provádět paralelní lookupy.
    - Typicky vytvářen automaticky v `RolePermissionSchemaExtension`
      a uložen do `info.context`, odkud si jej berou další extensiony
      (např. `UserRoleProviderExtension`).
    """

    def __init__(self, gql_client, base_query_str: str, cache_map=None):
        super().__init__(cache=True, cache_map=cache_map)
        self.gql_client = gql_client
        self.base_query_str = base_query_str

    def load(self, key):
        frozenkey = frozenset(key.items())
        # frozenkey = freeze_key(key)
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
        result = await self.gql_client(query=query, variables=variables)
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

USER_CAN_NOSTATE_CACHE = L1TTLCache(ttl_seconds=10, maxsize=20_000)
USER_CAN_STATE_CACHE   = L1TTLCache(ttl_seconds=10, maxsize=20_000)
USER_ROLES_CACHE       = L1TTLCache(ttl_seconds=30, maxsize=20_000)

class RolePermissionSchemaExtension(SchemaExtension):
    """
    Schema extension, která při každém GraphQL requestu připraví v kontextu
    batch loadery pro práci s RBAC/UG službou.

    Konkrétně v `on_execute()`:

    - Z `context.context` vezme GraphQL klienta `ug_client`.
    - Vytvoří tři `GraphQLBatchLoader` instance s různými dotazy:

        1) `userCanWithoutState_loader` (TestNoStateAccessQuery)
           - dotaz: userCanWithoutState(userId, rolesNeeded)
           - odpovídá na otázku: „Má uživatel nějakou z těchto rolí na daném RBAC objektu?“

        2) `userCanWithState_loader` (TestStateAccessQuery)
           - dotaz: userCanWithState(userId, access, stateId)
           - používá se pro přístup, který závisí i na typu přístupu / stavu.

        3) `userRolesForRBACQuery_loader` (GetUserRolesForRBACQuery)
           - dotaz: roles(userId)
           - vrací seznam všech rolí uživatele na daném RBAC objektu,
             včetně informací o roletype a skupině.

    - Tyto loadery uloží do `context.context` pod klíči:
        - `"userCanWithoutState_loader"`
        - `"userCanWithState_loader"`
        - `"userRolesForRBACQuery_loader"`

    Ostatní extensions (např. `UserRoleProviderExtension`) pak tyto loadery
    používají k efektivnímu batchovému dotazování na UG/RBAC systém v rámci
    jednoho GraphQL requestu.
    """
    
    async def on_execute(self):
        context = self.execution_context
        gqlClient = context.context.get("ug_client", None)
        # assert gqlClient is not None, "ug_client must be provided in context"
        loader = GraphQLBatchLoader(gqlClient, TestNoStateAccessQuery, cache_map=USER_CAN_NOSTATE_CACHE)
        context.context["userCanWithoutState_loader"] = loader
        loader = GraphQLBatchLoader(gqlClient, TestStateAccessQuery, cache_map=USER_CAN_STATE_CACHE)
        context.context["userCanWithState_loader"] = loader
        loader = GraphQLBatchLoader(gqlClient, GetUserRolesForRBACQuery, cache_map=USER_ROLES_CACHE)
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

