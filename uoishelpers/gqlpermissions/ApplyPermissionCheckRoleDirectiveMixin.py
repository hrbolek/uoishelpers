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
    roles: list[str]  # parametr, můžeš předat povolené role
    rbacrelated: bool = True

class ApplyPermissionCheckRoleDirectiveMixin:
    def apply(self, field):
        # Pokud pole ještě direktivu nemá, přidáme ji automaticky
        has_directive = any(isinstance(d, PermissionCheckRoleDirective) for d in field.directives)

        if not has_directive:
            directive_instance = PermissionCheckRoleDirective(roles=self.roles)
            # Přidáme direktivu do pole
            field.directives.append(directive_instance)
