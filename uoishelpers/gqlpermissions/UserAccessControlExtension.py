import typing
import strawberry

from .TwoStageGenericBaseExtension import TwoStageGenericBaseExtension
from .CallNextMixin import CallNextMixin
from .ApplyPermissionCheckRoleDirectiveMixin import ApplyPermissionCheckRoleDirectiveMixin

class UserAccessControlExtension(TwoStageGenericBaseExtension, ApplyPermissionCheckRoleDirectiveMixin, CallNextMixin):
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
