import strawberry

MISSING = object()

from .RbacProviderExtension import RbacProviderExtension
class RbacInsertProviderExtension(RbacProviderExtension):
    """
    Field extension určená pro INSERT operace, která získává `rbacobject_id`
    přímo z INPUT objektu a předává ho resolveru jako argument `rbacobject_id`.

    Použití:
    - Typicky se používá tam, kde RBAC objekt ještě neexistuje v databázi,
      a tedy nelze použít `RbacProviderExtension`, která pracuje s `db_row`.
    - Vstupní datová struktura (např. `MyInsertInput`) musí mít atribut
      se jménem odpovídajícím `rbac_key_name` (standardně `"rbacobject_id"`).

    Chování:

    - Konstruktor:
      - Parametr `rbac_key_name` říká, jak se v inputu jmenuje atribut obsahující
        RBAC objekt. Výchozí hodnota je `"rbacobject_id"`.
      - Na rozdíl od `RbacProviderExtension` už zde nepracujeme s `db_row`.

    - V `provide_rbac_object_id()`:
      - Vezme první hodnotu z `kwargs` (typicky `input` objekt).
      - Pokusí se z něj přečíst atribut jménem `rbac_key_name`.
      - Vrací jednu z hodnot:
        - nalezený `rbacobject_id`,
        - `MISSING`, pokud atribut v inputu neexistuje.

    - V `resolve_async()`:
      1. Z inputu si vezme `input_params` (první položka `kwargs`),
         aby je mohl vracet v chybové odpovědi.
      2. Zavolá `provide_rbac_object_id(...)` a získá `rbacobject_id`.
      3. Pokud je výsledek `MISSING`:
         - znamená to, že input objekt atribut vůbec neobsahuje,
           → vrací chybu `"rbacobject_id is not defined on input structure"`.
      4. Pokud je `rbacobject_id` rovno `None`:
         - atribut existuje, ale není nastaven,
           → vrací chybu `"rbacobject_id is not set in input structure"`.
      5. Při úspěchu zavolá `next_(...)` a doplní argument
         `rbacobject_id=rbacobject_id` do volání resolveru.

    Poznámky k použití v RBAC pipeline:

    - Používá se jako protějšek `RbacProviderExtension` u updaterů.
    - V seznamu `extensions=[...]` se obvykle umisťuje tak,
      aby byla spuštěna *před* `UserRoleProviderExtension`
      (která z `rbacobject_id` potřebuje vytvořit dotaz)
      a *před* `UserAccessControlExtension`.
    - Typická sestava pro INSERT:

        extensions = [
            UserAccessControlExtension(...),     # poslední krok — kontrola
            UserRoleProviderExtension(...),      # krok předtím — načtení rolí
            RbacInsertProviderExtension(...),    # jako první — získání rbacobject_id
        ]

      Protože Strawberry spouští extensions od poslední k první, tento zápis
      zajistí správné pořadí v běhu programu.
    """
    def __init__(self, rbac_key_name="rbacobject_id"):
        self.rbac_key_name = rbac_key_name

    async def provide_rbac_object_id(self, source, info: strawberry.types.Info, *args, **kwargs):
        input_params = next(iter(kwargs.values()), None)
        rbacobject_id = getattr(input_params, self.rbac_key_name, MISSING)
        return rbacobject_id
    
    async def resolve_async(self, next_, source, info: strawberry.types.Info, *args, **kwargs):
        input_params = next(iter(kwargs.values()), None)
        
        rbacobject_id = await self.provide_rbac_object_id(
            source, info, *args, **kwargs)
        # rbacobject_id = "8191cee1-8dba-4a2a-b9af-3f986eb0b51a"
        if rbacobject_id == MISSING:
            return self.return_error(
                info=info,
                message="rbacobject_id is not defined on input structure",
                code="77a75382-ee87-4ddf-aed1-8be379dfa1bf",
                input_data=input_params
            )        

        if rbacobject_id is None:
            return self.return_error(
                info=info,
                message="rbacobject_id is not set in input structure",
                code="e12dd4fe-bcf2-4ff9-837f-b5a2950597f9",
                input_data=input_params
            )        
        # return await self.call_next_resolve(next_, source, info, rbacobject_id=rbacobject_id, *args, **kwargs)
        return await next_(source, info, rbacobject_id=rbacobject_id, *args, **kwargs)

        
