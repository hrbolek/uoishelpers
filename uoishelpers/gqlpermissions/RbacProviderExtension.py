import strawberry

MISSING = object()

from .TwoStageGenericBaseExtension import TwoStageGenericBaseExtension
from .CallNextMixin import CallNextMixin
class RbacProviderExtension(TwoStageGenericBaseExtension, CallNextMixin):
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

        
