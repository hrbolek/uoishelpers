import strawberry

MISSING = object()

from .RbacProviderExtension import RbacProviderExtension
class RbacInsertProviderExtension(RbacProviderExtension):
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

        
