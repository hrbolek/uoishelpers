from strawberry.extensions import SchemaExtension

class SessionCommitExtension(SchemaExtension):
    
    def __init__(self, session_maker_factory, loaders_factory):
        super().__init__()
        self._session_maker_factory = session_maker_factory
        self.loaders_factory = loaders_factory

    async def on_operation(self):
        
        asyncSessionMaker = await self._session_maker_factory()
        

        async with asyncSessionMaker() as session:
            try:
            # před spuštěním operace
                self.execution_context.context["session"] = session
                self.execution_context.context["errors"] = []
                loaders_context = self.loaders_factory(session)
                self.execution_context.context.update(loaders_context)
                print("Starting session", flush=True)
                yield  
                # print(f'Closing operation {self.execution_context.context}')
                # po dokončení operace:

                if self.execution_context.context["errors"]:
                    await session.rollback()
                    print("Rollback session due to error flag", flush=True)
                else:
                    await session.commit()
                    print("Commit session", flush=True)
            except Exception as e:
                print(f"Exception during operation {e}, doing rollback", flush=True)
                error_description = {
                    "msg": f"Unexpected error during operation: {e}",
                    "code": "43b027da-d073-4fac-8881-3353609f2bcd",
                    "_input": {}
                }
                self.execution_context.context["errors"].append(error_description)
                await session.rollback()
                raise e
            
def SessionCommitExtensionFactory(*, session_maker_factory, loaders_factory, SessionCommitExtension=SessionCommitExtension):
    return SessionCommitExtension(
            session_maker_factory=session_maker_factory,
            loaders_factory=loaders_factory,
        )