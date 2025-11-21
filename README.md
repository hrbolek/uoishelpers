# Library for usefull utitilies use in _uois

pytest --cov-report term-missing --cov=uoishelpers tests



# RBAC – souhrnné zhodnocení řešení

Tento projekt implementuje řízení přístupu (RBAC) nad GraphQL API pomocí
kombinace Strawberry field extensions, schema extension a GraphQL batch loaderů.

## Architektura

### 1. Základní stavební bloky

- **TwoStageGenericBaseExtension**
  - Společná základna pro všechny RBAC extensions.
  - Umožňuje typově bezpečné napojení na `ErrorType` a `GQLModel`.
  - Poskytuje jednotný způsob vracení chyb (`return_error`) včetně:
    - chybového kódu (`code`),
    - původních vstupních dat (`_input`),
    - umístění v GraphQL dotazu (`location`).

- **CallNextMixin**
  - Zjednodušuje volání další extension / resolveru.
  - Umožňuje skládat více extensions přes MRO bez nutnosti ručně řešit,
    zda volat `super().resolve_async` nebo `next_`.

### 2. Načítání dat a RBAC objektů

- **LoadDataExtension**
  - Načte z databáze řádek (`db_row`) podle primárního klíče z inputu.
  - `db_row` je předán resolveru jako interní argument, ale není vidět v API.
  - Typicky je **poslední** v seznamu `extensions=[...]`, aby se vykonala jako první.

- **RbacProviderExtension**
  - Z `db_row` získává `rbacobject_id`.
  - Pokud chybí speciální `rbacobject_id`, používá fallback `db_row.id`.
  - Předává `rbacobject_id` dál jako interní argument pro další extensions.

- **RbacInsertProviderExtension**
  - Varianta pro INSERT operace.
  - Čte `rbacobject_id` přímo z inputu, protože ještě neexistuje `db_row`.

### 3. Získání rolí a kontrola přístupu

- **UserRoleProviderExtension**
  - Na základě `rbacobject_id` a uživatele z kontextu volá UG/RBAC GraphQL API.
  - Používá batch loader `userRolesForRBACQuery_loader` pro efektivní dotazování.
  - Resolveru předává `user_roles` jako interní argument.

- **UserAccessControlExtension**
  - Finální RBAC kontrola pro **objektově vázané** oprávnění.
  - Ověřuje, zda alespoň jedna role v `user_roles` odpovídá požadovaným typům (`roles`).
  - V případě neúspěchu vrací standardizovanou chybovou odpověď „you are not authorized“.
  - Dědí z `ApplyPermissionCheckRoleDirectiveMixin` → do schématu přidává
    direktivu `@permissionCheckRole(roles=[...], rbacrelated=True)`.

- **UserAbsoluteAccessControlExtension**
  - Kontrola **globálních** rolí uživatele (bez vazby na konkrétní RBAC objekt).
  - Role čte přímo z `user["roles"]` v kontextu.
  - Do schématu přidává `@permissionCheckRole(roles=[...], rbacrelated=False)`.

### 4. Schema direktivy a mixiny

- **PermissionCheckRoleDirective**
  - Schema direktiva (Strawberry federation directive) použitelná na field:
    - `roles: [String!]` – jaké role mají k poli přístup,
    - `rbacrelated: Boolean` – zda jde o objektovou (True) nebo globální (False) kontrolu.
  - Používá se pro dokumentaci a introspekci schématu.

- **ApplyPermissionCheckRoleDirectiveMixin**
  - Mixin pro extensions, které chtějí automaticky přidat `PermissionCheckRoleDirective`
    na pole podle konfigurace `self.roles`.

### 5. Schema extension a batchování GraphQL dotazů

- **GraphQLBatchLoader**
  - Obecný `DataLoader` pro batchování GraphQL dotazů.
  - Přijímá klíče jako slovníky parametrů (`{"id": ..., "user_id": ...}`),
    převádí je na hashovatelné `frozenset`.
  - Klíče se seskupují podle parametrů **mimo `id`**, a pro každou skupinu se
    vytvoří jeden GraphQL dotaz s aliasovanými fieldy (`item1`, `item2`, ...).
  - Odpověď se rozbalí zpět do listu ve správném pořadí.

- **RolePermissionSchemaExtension (SchemaExtension)**
  - V lifecycle hooku `on_execute()` připraví v `info.context` následující loadery:
    - `userCanWithoutState_loader` – dotaz `TestNoStateAccessQuery`
    - `userCanWithState_loader` – dotaz `TestStateAccessQuery`
    - `userRolesForRBACQuery_loader` – dotaz `GetUserRolesForRBACQuery`
  - Ostatní extensions (`UserRoleProviderExtension`, případně další) tyto loadery
    používají k efektivnímu dotazování na UG/RBAC API v rámci jednoho requestu.

## Typické RBAC pipelines

### Update operace nad existující entitou

Logický průběh:
1. Načíst `db_row` podle `input.id`.
2. Z `db_row` získat `rbacobject_id`.
3. Z UG/RBAC API získat `user_roles`.
4. Zkontrolovat oprávnění.
5. Spustit resolver.

Deklarace (pořadí v seznamu je **obrácené** oproti běhu):

```python
extensions = [
    UserAccessControlExtension[ErrorType, Model](roles=[...]),
    UserRoleProviderExtension[ErrorType, Model](),
    RbacProviderExtension[ErrorType, Model](),
    LoadDataExtension[ErrorType, Model](),
]

### Insert operace s RBAC

Logický průběh:
1. Vzít rbacobject_id z inputu.
2. Získat user_roles z UG/RBAC API.
3. Ověřit oprávnění.
4. Spustit resolver.

Deklarace:
```python
extensions = [
    UserAccessControlExtension[ErrorType, Model](roles=[...]),
    UserRoleProviderExtension[ErrorType, Model](),
    RbacInsertProviderExtension[ErrorType, Model](),
]
```

### Globální oprávnění (bez RBAC objektu)

Deklarace:
```python
extensions = [
    UserAbsoluteAccessControlExtension[ErrorType, Model](roles=["administrátor"]),
]
```

### Silné stránky řešení

- Modularita: RBAC je složen z malých, znovupoužitelných extensions (načtení dat, získání RBAC ID, získání rolí, kontrola).

- Jasné oddělení odpovědností:

    - jedna extension = jeden krok pipeline,

    - snadná možnost rozšíření nebo výměny jednotlivých kroků.

- Výkon:

    - batchování GraphQL dotazů pomocí GraphQLBatchLoader,

    - snížení počtu volání na UG/RBAC systém.

- Konzistence chyb:

    - společná logika v TwoStageGenericBaseExtension.return_error,

    - jednotný formát chyb napříč celým API.

- Dokumentace v GraphQL schématu:

    - direktiva @permissionCheckRole umožňuje klientům i nástrojům vidět, která pole jsou chráněná a jaké role jsou vyžadovány.

### Omezení a doporučení

- Pořadí extensions v extensions=[...] je potřeba pečlivě hlídat:

    - Strawberry je spouští od poslední k první.

- Při konfiguraci je nutné zajistit:

    - přítomnost ug_client v kontextu pro RolePermissionSchemaExtension,

    - správné naplnění uživatele v kontextu (getUserFromInfo),

    - existenci ErrorType a GQLModel pro všechny specializované extensions.

- Další rozšíření:

    - jemnější logika pro expiraci rolí (valid, startdate, enddate),

    - detailnější logování neúspěšných autorizací.

Tento systém poskytuje robustní, modulární a rozšiřitelné RBAC řešení nad GraphQL, které je vhodné pro větší aplikace s komplexními přístupovými pravidly.