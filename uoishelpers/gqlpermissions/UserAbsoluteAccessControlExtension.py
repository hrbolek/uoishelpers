import uuid
import typing
import strawberry

from .TwoStageGenericBaseExtension import TwoStageGenericBaseExtension
from .CallNextMixin import CallNextMixin
from .ApplyPermissionCheckRoleDirectiveMixin import PermissionCheckRoleDirective
from ..resolvers import getUserFromInfo

class UserAbsoluteAccessControlExtension(TwoStageGenericBaseExtension, CallNextMixin):
    """
    Field extension určená pro **globální kontrolu přístupu** – tedy takovou,
    která **není** vázaná na žádný konkrétní RBAC objekt. Místo toho pracuje
    pouze s globálními rolemi uživatele, které jsou uloženy v `info.context`
    (typicky `"user": {"roles": [...]}`).

    Použití:
    - Hodí se pro operace, které nejsou navázané na konkrétní objekt ani
      databázový řádek – např. generické administrátorské operace.
    - Na rozdíl od `UserAccessControlExtension` nepotřebuje `rbacobject_id`
      ani `UserRoleProviderExtension`.

    ----------------------------------------------------------------------
    CHOVÁNÍ
    ----------------------------------------------------------------------

    Konstruktor:
    - `roles: list[str]`
      - seznam názvů roletype, které jsou povoleny pro provedení operace
        (např. `["administrátor"]`, `["administrátor", "superuser"]`).

    ----------------------------------------------------------------------

    apply(self, field):
    - Automaticky přidá schema direktivu
        @permissionCheckRole(roles=[...], rbacrelated=False)
      pokud ji pole ještě nemá.
    - Tím se informace o požadovaných globálních rolích objeví ve schématu.
    - Stejně jako ostatní extensions odebere z GraphQL API parametr
      `user_roles`, i když jej resolver může mít v signatuře
      a extension jej tam později vloží.

    ----------------------------------------------------------------------

    resolve_async(...):
    1. Pomocí `getUserFromInfo(info)` načte uživatelský objekt z kontextu.
    2. Získá seznam globálních rolí uživatele (`user["roles"]`).
       - Pokud `roles` v uživateli chybí → assert chyba konfigurace.
    3. Najde průnik globálních rolí uživatele s požadovanými rolovými typy:

           matched_roles = [
               role for role in user_roles
               if role["roletype"]["name"] in self.roles
           ]

    4. Pokud je průnik neprázdný:
       - Význam: uživatel má oprávnění k operaci.
       - `user_roles` vloží do `kwargs` a zavolá další extension / resolver
         přes `call_next_resolve(...)`.

    5. Pokud průnik prázdný:
       - uživatel nemá globální oprávnění k akci,
       - vrací chybový objekt přes `return_error(...)` s hláškou
         „you are not authorized“.

    ----------------------------------------------------------------------
    TYPICKÉ UMÍSTĚNÍ V PIPELINE
    ----------------------------------------------------------------------

    Protože globální oprávnění nepotřebuje žádné další údaje (nedotazuje se
    na RBAC objekt ani nevyžaduje rbacobject_id, db_row, atd.), bývá
    v seznamu `extensions=[...]` obvykle *jedinou* nebo *první* položkou:

        extensions = [
            UserAbsoluteAccessControlExtension(roles=["administrátor"]),
        ]

    Strawberry vyhodnocuje extensions od poslední k první, ale protože tato
    extension nemá závislosti, umístění v seznamu je zpravidla jednoduché.

    ----------------------------------------------------------------------
    SHRNUTÍ

    - Zajišťuje autorizaci pouze podle **globálních** rolí uživatele.
    - Nepotřebuje RBAC objekt ani další extensions.
    - Vkládá `@permissionCheckRole(..., rbacrelated=False)` do schématu.
    - Pokud uživatel nemá požadovanou roli → vrací standardizovanou GraphQL chybu.
    - Je ideální pro administrátorské operace a operace mimo RBAC kontext.
    """    
    def __init__(self, *, roles: list[str]):
        self.roles = roles
        super().__init__()

    def apply(self, field):
        # Pokud pole ještě direktivu nemá, přidáme ji automaticky
        has_directive = any(isinstance(d, PermissionCheckRoleDirective) for d in field.directives)

        if not has_directive:
            directive_instance = PermissionCheckRoleDirective(roles=self.roles, rbacrelated=False)
            # Přidáme direktivu do pole
            field.directives.append(directive_instance)


        graphql_disabled_vars = {"user_roles"}
        field_arg_names = {arg.python_name for arg in field.arguments}
        missing_args = graphql_disabled_vars - field_arg_names

        # print(f"UserRoleProviderExtension.field_arg_names {field.name} {field_arg_names} / {missing_args} \n\t@ {self}[{self.id}: {self.counter}]")
        # if missing_args:
        #     raise RuntimeError(
        #         f"Field {field.name} is missing expected arguments for extension {self.__class__.__name__}: {missing_args}"
        #     )

        field.arguments = [arg for arg in field.arguments if arg.python_name not in graphql_disabled_vars]


    async def resolve_async(self, next_, source, info: strawberry.types.Info, *args, **kwargs):
        input_params = next(iter(kwargs.values()), None)
        user = getUserFromInfo(info=info)
        user_roles = user.get("roles")

        assert user_roles is not None, f"user in context must have roles attribute, check configuration"
        matched_roles = [role for role in user_roles if role["roletype"]["name"] in self.roles]

        if matched_roles:
            user_roles = matched_roles
            kwargs["user_roles"] = user_roles
            return await self.call_next_resolve(next_, source, info, user_roles=user_roles, *args, **kwargs)    

        return self.return_error(
            info=info,
            message="you are not authorized",
            code="468e8391-06a7-468e-a659-3d07bb83c977",
            input_data=input_params
        )        
