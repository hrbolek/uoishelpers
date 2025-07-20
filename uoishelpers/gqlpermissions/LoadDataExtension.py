import strawberry
import uuid
from .TwoStageGenericBaseExtension import TwoStageGenericBaseExtension
from .CallNextMixin import CallNextMixin
class LoadDataExtension(TwoStageGenericBaseExtension, CallNextMixin):
    def __init__(self, *, primary_key_name: str = "id"):
        self.primary_key_name = primary_key_name
        super().__init__()

    def apply(self, field):
        graphql_disabled_vars = {"db_row"}
        field_arg_names = {arg.python_name for arg in field.arguments}
        missing_args = graphql_disabled_vars - field_arg_names
        # if missing_args:
        #     raise RuntimeError(
        #         f"Field {field.name} is missing expected arguments for extension {self.__class__.__name__}: {missing_args}"
        #     )

        field.arguments = [arg for arg in field.arguments if arg.python_name not in graphql_disabled_vars]

    async def resolve_async(self, next_, source, info: strawberry.types.Info, *args, **kwargs):
        # print(f"LoadDataExtension.kwargs {kwargs}")
        input_params = next(iter(kwargs.values()), None)
        if input_params is None:
            return self.return_error(
                info=info,
                message="No input parameters provided",
                code="c4e3cd62-64a9-458d-8d88-e76629be1307",
                input_data=input_params
            )
        # print(f"input_params: {input_params} ({type(input_params)})", flush=True)
        id = getattr(input_params, self.primary_key_name, None) if not isinstance(input_params, uuid.UUID) else input_params
        if id is None:
            return self.return_error(
                info=info,
                message="id is required in input parameters",
                code="a849f652-663b-4658-b594-920b7b9355c6",
                input_data=input_params
            )
        
        loader = getattr(input_params, "getLoader", None)
        if loader is None:
            loader = self.GQLModel.getLoader(info)
        else:
            loader = loader(info=info)
        
        if not loader:
            return self.return_error(
                info=info,
                message="Input parameters do not have a method getLoader providing a valid loader",
                code="e866b8c6-2771-4eb5-a25e-92f7dce1cf8d",
                input_data=input_params
            )

        db_row = await loader.load(id)
        if db_row is None:
            return self.return_error(
                info=info,
                message="data not found in database table",
                code="a8c2c427-681b-4d46-8d9f-4b833f0c0051",
                input_data=input_params
            )
        # print(f"LoadDataExtension.kwargs 2 {kwargs}")
        # return await self.call_next_resolve(next_, source, info, db_row=db_row, *args, **kwargs)
        return await next_(source, info, db_row=db_row, *args, **kwargs)
        
