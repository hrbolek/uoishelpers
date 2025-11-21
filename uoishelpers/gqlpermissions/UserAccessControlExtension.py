import typing
import strawberry

from .TwoStageGenericBaseExtension import TwoStageGenericBaseExtension
from .CallNextMixin import CallNextMixin
from .ApplyPermissionCheckRoleDirectiveMixin import ApplyPermissionCheckRoleDirectiveMixin

class UserAccessControlExtension(TwoStageGenericBaseExtension, ApplyPermissionCheckRoleDirectiveMixin, CallNextMixin):
    """
    Field extension, která provádí finální RBAC kontrolu přístupu na základě
    rolí uživatele (`user_roles`) a seznamu povolených rolí (`self.roles`).

    V RBAC pipeline je to „poslední brána“:
    - před ní už byly načteny role uživatele pro daný RBAC objekt
      (`UserRoleProviderExtension`),
    - tady se rozhodne, jestli uživatel smí danou operaci provést.

    Konstruktor:

    - `roles: list[str]`
      - seznam „povolených“ roletype jmen (např. `["administrátor", "editor"]`),
      - extension ověří, zda uživatel má alespoň jednu roli, jejíž
        `roletype.name` je v tomto seznamu.

    Vztah k direktivě:

    - Třída dědí z `ApplyPermissionCheckRoleDirectiveMixin`:
      - ten v metodě `apply()` (zděděné z mixinu) automaticky přidává na field
        schema direktivu `@permissionCheckRole(roles=[...], rbacrelated=True)`
        podle `self.roles`, pokud tam ještě není.
      - Tím se informace o požadovaných rolích dostane také do GraphQL schématu
        (např. pro dokumentaci nebo další nástroje).

    Chování v `resolve_async()`:

    1. Z `kwargs` si vezme `input_params` (první hodnotu) pro případné chybové
       hlášení.
    2. Vytáhne `user_roles = kwargs.get("user_roles", None)`:
       - tento parametr musí být předem doplněn `UserRoleProviderExtension`,
       - pokud není k dispozici (`None`), vyhodí `assert` s hláškou
         „Bad configuration of field extensions, missing UserRoleProviderExtension“,
         což signalizuje špatně poskládané `extensions=[...]`.
    3. Najde průnik uživatelských rolí s povolenými rolovými typy:

           matched_roles = [
               role for role in user_roles
               if role["roletype"]["name"] in self.roles
           ]

    4. Pokud `matched_roles` není prázdné:
       - přepíše `kwargs["user_roles"] = matched_roles` (tj. dál pouští jen
         ty role, které skutečně odpovídají požadovaným),
       - zavolá `self.call_next_resolve(...)` a pustí požadavek dál
         (na další extensions / resolver).
    5. Pokud žádná role nevyhovuje:
       - vrátí chybový objekt pomocí `return_error(...)` s hláškou
         „you are not authorized“.

    Použití v RBAC pipeline:

    - Resolver musí mít signaturu s parametrem `user_roles`, ale díky mixinu
      a `apply()` se tento parametr odstraní z `field.arguments`, takže
      **není viditelný v GraphQL API**, ale resolver ho dostane.
    - Typická sestava extensions pro update může vypadat takto:

        extensions = [
            UserAccessControlExtension(...),     # poslední krok - kontrola oprávnění
            UserRoleProviderExtension(...),      # načtení user_roles z RBAC API
            RbacProviderExtension(...),          # získání rbacobject_id z db_row
            LoadDataExtension(...),              # načtení db_row podle input.id
        ]

      Vzhledem k tomu, že Strawberry spouští extensions **od poslední k první**,
      běží reálné pořadí takto:
      - nejdříve `LoadDataExtension`,
      - pak `RbacProviderExtension`,
      - potom `UserRoleProviderExtension`,
      - nakonec `UserAccessControlExtension` a resolver.

    Shrnutí:

    - `UserAccessControlExtension` je místo, kde se definitivně rozhodne,
      zda má uživatel přístup na základě jeho rolí vůči RBAC objektu.
    - Očekává, že někdo před ní už naplnil `user_roles` a `rbacobject_id`.
    - Pokud žádná z rolí uživatele neodpovídá požadovaným `roles`, vrací
      standardizovanou chybovou odpověď přes `return_error(...)`.
    """
    def __init__(self, *, roles: list[str]):
        self.roles = roles
        super().__init__()

    async def resolve_async(self, next_, source, info: strawberry.types.Info, *args, **kwargs):
        input_params = next(iter(kwargs.values()), None)
        user_roles = kwargs.get("user_roles", None)        
        
        assert user_roles is not None, f"Bad configuration of field extensions, missing UserRoleProviderExtension"
        matched_roles = [role for role in user_roles if role["roletype"]["name"] in self.roles]
        if matched_roles:
            kwargs["user_roles"] = matched_roles
            return await self.call_next_resolve(next_, source, info, *args, **kwargs)    

        return self.return_error(
            info=info,
            message="you are not authorized",
            code="468e8391-06a7-468e-a659-3d07bb83c977",
            input_data=input_params
        )        
