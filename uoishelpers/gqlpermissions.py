import os
import strawberry
from strawberry.types.base import StrawberryList
from functools import cached_property

def getUserFromInfo(info: strawberry.types.Info):
    result = info.context.get("user", None)
    if result is None:
        request = info.context.get("request", None)
        assert request is not None, "request should be in context, something is wrong"
        result = request.scope.get("user", None)
    assert result is not None, "User is wanted but not present in context or in request.scope, check it"
    return result

class OnlyForAuthentized(strawberry.permission.BasePermission):
    message = "User is not authenticated"

    async def has_permission(
        self, source, info: strawberry.types.Info, **kwargs
    ) -> bool:
        if self.isDEMO:
            # print("DEMO Enabled, not for production")
            return True
        
        self.defaultResult = [] if info._field.type.__class__ == StrawberryList else None
        user = getUserFromInfo(info)
        return (False if user is None else True)
    
    def on_unauthorized(self):
        return self.defaultResult
        
    @cached_property
    def isDEMO(self):
        DEMO = os.getenv("DEMO", None)
        return DEMO == "True"

