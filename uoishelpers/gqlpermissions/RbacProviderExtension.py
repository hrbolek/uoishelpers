import strawberry

MISSING = object()

from .TwoStageGenericBaseExtension import TwoStageGenericBaseExtension
from .CallNextMixin import CallNextMixin
class RbacProviderExtension(TwoStageGenericBaseExtension, CallNextMixin):
    """
    Field extension, která před voláním resolveru zjistí `rbacobject_id`
    pro daný databázový řádek (`db_row`) a předá ho resolveru jako argument
    `rbacobject_id`.

    Typický kontext použití:
    - `db_row` byl už předtím načten jinou extension (např. `LoadDataExtension`)
      a je předán v `kwargs`.
    - Pro RBAC kontrolu potřebujeme znát identifikátor RBAC objektu (`rbacobject_id`),
      který je uložený buď:
        - jako atribut `rbacobject_id` na `db_row`, nebo
        - pokud je `rbacobject_id` None, tak se použije fallback `db_row.id`.

    Chování:

    - V `apply()`:
      - Očekává, že rozšířený resolver má v signatuře parametr `rbacobject_id`.
      - Tento parametr odstraní z `field.arguments`, takže se v GraphQL schématu
        neobjeví (klient ho neposílá), ale resolver ho přesto dostane jako
        pojmenovaný argument.
    
    - V `provide_rbac_object_id()`:
      - Z `kwargs` vezme `db_row` (nebo `MISSING`, pokud chybí).
      - Pokusí se z `db_row` přečíst atribut `rbacobject_id`.
      - Vrací jednu z hodnot:
        - konkrétní `rbacobject_id`,
        - `MISSING`, pokud atribut neexistuje.

    - V `resolve_async()`:
      1. Z input parametrů (první hodnota v `kwargs`) si vezme `input_params`,
         aby je mohl případně použít v chybové zprávě.
      2. Zavolá `provide_rbac_object_id(...)` a získá `rbacobject_id`.
      3. Pokud je výsledek `MISSING`:
         - vrátí chybu `return_error(...)` s hláškou
           `"rbacobject_id is not defined on data_row"`.
      4. Pokud je `rbacobject_id` rovno `None`:
         - pokusí se použít `db_row.id` jako fallback,
         - pokud je výsledkem opět `None`, vrací chybu
           `"rbacobject_id is not set in data_row"`.
      5. Při úspěchu zavolá `next_(...)` a předá dál argument
         `rbacobject_id=rbacobject_id` spolu se všemi původními `*args, **kwargs`.

    Použití:

    - Resolver musí mít v signatuře parametr `rbacobject_id`, ale v GraphQL schématu
      se tento argument neobjeví (extension ho skryje).
    - V typické RBAC pipeline je `RbacProviderExtension` v seznamu `extensions=[...]`
      zapsaná tak, aby se spustila až po načtení `db_row` (např. po `LoadDataExtension`),
      ale ještě před extensions, které `rbacobject_id` potřebují (např.
      `UserRoleProviderExtension`):
      
        extensions = [
            UserAccessControlExtension(...),
            UserRoleProviderExtension(...),
            RbacProviderExtension(...),
            LoadDataExtension(...),
        ]

      Vzhledem k tomu, že Strawberry volá extensions od poslední k první, proběhne
      nejdříve `LoadDataExtension`, pak `RbacProviderExtension`, potom
      `UserRoleProviderExtension` a nakonec `UserAccessControlExtension` i resolver.
    """    
    def apply(self, field):
        graphql_disabled_vars = {"rbacobject_id"}
        field_arg_names = {arg.python_name for arg in field.arguments}
        missing_args = graphql_disabled_vars - field_arg_names
        # if missing_args:
        #     raise RuntimeError(
        #         f"Field {field.name} is missing expected arguments for extension {self.__class__.__name__}: {missing_args}"
        #     )

        field.arguments = [arg for arg in field.arguments if arg.python_name not in graphql_disabled_vars]

    async def provide_rbac_object_id(self, source, info: strawberry.types.Info, *args, **kwargs):
        db_row = kwargs.get("db_row", MISSING)
        rbacobject_id = getattr(db_row, "rbacobject_id", MISSING)
        return rbacobject_id
    
    async def resolve_async(self, next_, source, info: strawberry.types.Info, *args, **kwargs):
        input_params = next(iter(kwargs.values()), None)
        
        rbacobject_id = await self.provide_rbac_object_id(
            source, info, *args, **kwargs)
        # rbacobject_id = "8191cee1-8dba-4a2a-b9af-3f986eb0b51a"
        if rbacobject_id == MISSING:
            return self.return_error(
                info=info,
                message="rbacobject_id is not defined on data_row",
                code="a9a36c0b-aa44-455b-9f5e-67aa2fd34ec1",
                input_data=input_params
            )        

        if rbacobject_id is None:
            db_row = kwargs.get("db_row", MISSING)
            rbacobject_id = getattr(db_row, "id", None)
        if rbacobject_id is None:
            return self.return_error(
                info=info,
                message="rbacobject_id is not set in data_row",
                code="00f53a67-3973-4986-b4ee-5939c21da684",
                input_data=input_params
            )        
        # return await self.call_next_resolve(next_, source, info, rbacobject_id=rbacobject_id, *args, **kwargs)
        return await next_(source, info, rbacobject_id=rbacobject_id, *args, **kwargs)

        
