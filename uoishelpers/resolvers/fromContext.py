import strawberry

def getUserFromInfo(info: strawberry.types.Info):
    result = info.context.get("user", None)
    if result is None:
        request = info.context.get("request", None)
        assert request is not None, "request should be in context, something is wrong"
        result = request.scope.get("user", None)
    assert result is not None, "User is wanted but not present in context or in request.scope, check it"
    return result

def getLoadersFromInfo(info: strawberry.types.Info):
    result = info.context.get("loaders", None)
    assert result is not None, "Loaders are asked for but not present in context, check context preparation"
    return result

def getUgClientFromInfo(info: strawberry.types.Info):
    result = info.context.get("ug_client" None)
    assert result is not None, "You must use WhoAmIExtension"
    return result    