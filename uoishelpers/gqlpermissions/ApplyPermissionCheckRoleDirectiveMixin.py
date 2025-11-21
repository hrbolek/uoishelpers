import typing
import strawberry
from strawberry.federation.schema_directive import schema_directive, Location
from strawberry.directive import DirectiveLocation

@schema_directive(
    repeatable=True,
    compose=True,
    description="Označuje, že pole je chráněné a kontroluje oprávnění pomocí PermissionCheckRoleExtension",
    locations=[Location.FIELD_DEFINITION, DirectiveLocation.FIELD],
)
class PermissionCheckRoleDirective:
    """ 
    Schema direktiva pro GraphQL/Strawberry:
    - dá se použít na field (v SDL jako @permissionCheckRole)
    - nese informaci o tom, jaké role mají k poli přístup
    - rbacrelated říká, zda jde o RBAC-vázanou kontrolu (True) nebo globální (False)
    """ 
    roles: list[str]  # parametr, můžeš předat povolené role
    rbacrelated: bool = True

class ApplyPermissionCheckRoleDirectiveMixin:
    """
    Mixin pro field extensions, které chtějí automaticky přidat
    PermissionCheckRoleDirective na pole podle své konfigurace.
    
    V apply():
    - zkontroluje, zda pole už má PermissionCheckRoleDirective
    - pokud ne, vytvoří novou instanci s roles=self.roles
      a přidá ji do field.directives
    
    Používá se např. v UserAccessControlExtension, aby se informace
    o požadovaných rolích promítla i do GraphQL schématu.    
    """
    def apply(self, field):
        # Pokud pole ještě direktivu nemá, přidáme ji automaticky
        has_directive = any(isinstance(d, PermissionCheckRoleDirective) for d in field.directives)

        if not has_directive:
            directive_instance = PermissionCheckRoleDirective(roles=self.roles)
            # Přidáme direktivu do pole
            field.directives.append(directive_instance)
