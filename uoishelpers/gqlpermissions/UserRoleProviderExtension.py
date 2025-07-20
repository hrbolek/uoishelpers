import typing
import strawberry
from uoishelpers.resolvers import getUserFromInfo

from .TwoStageGenericBaseExtension import TwoStageGenericBaseExtension
from .CallNextMixin import CallNextMixin
MISSING = object()
class UserRoleProviderExtension(TwoStageGenericBaseExtension, CallNextMixin):

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
