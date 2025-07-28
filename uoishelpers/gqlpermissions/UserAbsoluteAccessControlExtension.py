import uuid
import typing
import strawberry

from .TwoStageGenericBaseExtension import TwoStageGenericBaseExtension
from .CallNextMixin import CallNextMixin
from .ApplyPermissionCheckRoleDirectiveMixin import PermissionCheckRoleDirective
from ..resolvers import getUserFromInfo

class UserAbsoluteAccessControlExtension(TwoStageGenericBaseExtension, CallNextMixin):
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
