import typing
import strawberry
from uoishelpers.resolvers import getUserFromInfo

from .TwoStageGenericBaseExtension import TwoStageGenericBaseExtension
from .CallNextMixin import CallNextMixin
MISSING = object()
class UserRoleProviderExtension(TwoStageGenericBaseExtension, CallNextMixin):
    """
    Field extension, která na základě `rbacobject_id` a uživatele z kontextu
    načte seznam rolí uživatele na daném RBAC objektu a předá ho resolveru
    jako argument `user_roles`.

    Tato extension tvoří střední krok RBAC pipeline:
    - `LoadDataExtension` nebo `RbacInsertProviderExtension` poskytne `db_row` nebo `rbacobject_id`,
    - `UserRoleProviderExtension` na základě `rbacobject_id` načte role uživatele,
    - `UserAccessControlExtension` rozhodne, zda má uživatel oprávnění.

    Chování:

    - V `apply()`:
      - Očekává, že resolver má v signatuře parametr `user_roles`.
      - Tento parametr odstraní z GraphQL definice argumentů (`field.arguments`),
        takže se v API neobjeví, ale resolver jej stále obdrží.
      - Je to stejné chování jako u ostatních extensions, které vkládají interní
        hodnoty do resolveru (např. `db_row`, `rbacobject_id`).

    - V `resolve_async()`:
      1. Z input parametrů (první položka v `kwargs`) vezme `input_params`,
         aby je mohl použít pro případné chybové hlášky.
      2. Z `kwargs` získá `rbacobject_id` – ten musí být už dříve vložen jinou extension.
         - Pokud je `rbacobject_id` `None`, vrací chybu
           `"rbacobject_id is not set in data_row"`.
      3. Z kontextu (`info.context`) načte `userRolesForRBACQuery_loader`.
         - Tento loader je připraven `RolePermissionSchemaExtension`
           během zpracování GraphQL requestu.
      4. Získá identitu uživatele pomocí `getUserFromInfo(info)`.
      5. Sestaví dotazovací parametry:

            {
                "id": rbacobject_id,
                "user_id": <id uživatele>
            }

      6. Zavolá `role_loader.load(params)` a očekává odpověď struktury:

            {"result": [...]}

         kde `result` je seznam rolí uživatele na daném RBAC objektu.
      7. Pokud odpověď neobsahuje `"result"`, vyvolá interní chybu (assert).
      8. Získané `user_roles` předá dál voláním:

            await self.call_next_resolve(
                next_, source, info, user_roles=user_roles, *args, **kwargs
            )

    Použití:

    - Resolver musí mít signaturu s parametrem `user_roles`, ale tento parametr nebude
      viditelný v GraphQL API.
    - Hodí se pro všechny operace, které mají RBAC logiku vázanou na objekt.
    - V typické RBAC pipeline se umisťuje **mezi** poskytovatele `rbacobject_id`
      (tj. mezi `RbacProviderExtension` / `RbacInsertProviderExtension`)
      a samotnou přístupovou kontrolu (`UserAccessControlExtension`):

        extensions = [
            UserAccessControlExtension(...),     # poslední krok (kontrola rolí)
            UserRoleProviderExtension(...),      # načtení rolí uživatele
            RbacProviderExtension(...),          # získání rbacobject_id
            LoadDataExtension(...),              # načtení db_row
        ]

      Protože Strawberry spouští extensions v obráceném pořadí, je takto zapsaná
      pipeline vykonána ve správném logickém sledu.
    """
    def apply(self, field):
        graphql_disabled_vars = {"user_roles"}
        field_arg_names = {arg.python_name for arg in field.arguments}
        print(f"UserRoleProviderExtension.field_arg_names {field_arg_names}")
        missing_args = graphql_disabled_vars - field_arg_names
        # if missing_args:
        #     raise RuntimeError(
        #         f"Field {field.name} is missing expected arguments for extension {self.__class__.__name__}: {missing_args}"
        #     )

        field.arguments = [arg for arg in field.arguments if arg.python_name not in graphql_disabled_vars]

    async def resolve_async(self, next_, source, info: strawberry.types.Info, *args, **kwargs):
        input_params = next(iter(kwargs.values()), None)
        rbacobject_id = kwargs.get("rbacobject_id", None)        
        # rbacobject_id = "8191cee1-8dba-4a2a-b9af-3f986eb0b51a"

        if rbacobject_id is None:
            return self.return_error(
                info=info,
                message="rbacobject_id is not set in data_row",
                code="00f53a67-3973-4986-b4ee-5939c21da684",
                input_data=input_params
            )        
        role_loader = info.context.get("userRolesForRBACQuery_loader", None)
        assert role_loader is not None, "userRolesForRBACQuery_loader must be provided in context"
        user = getUserFromInfo(info=info)
        params = {
            "id": rbacobject_id,
            "user_id": str(user["id"])
        }

        gql_response = await role_loader.load(params)
        assert gql_response is not None, f"query for user roles was not responded properly {gql_response}"
        assert "result" in gql_response, f"query for user roles was not responded properly {gql_response}"
        user_roles = gql_response["result"]
        return await self.call_next_resolve(next_, source, info, user_roles=user_roles, *args, **kwargs)
