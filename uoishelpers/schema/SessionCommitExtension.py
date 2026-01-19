import asyncio
import uuid
from strawberry.extensions import SchemaExtension

session_monitor = {}
DB_SEMAPHORE = asyncio.Semaphore(10)  # např. pool_size
class SessionCommitExtension(SchemaExtension):
    
    def __init__(self, session_maker_factory, loaders_factory):
        super().__init__()
        self._session_maker_factory = session_maker_factory
        self.loaders_factory = loaders_factory

    async def on_operation(self):
        id = uuid.uuid4()
        asyncSessionMaker = await self._session_maker_factory()
        

        async with asyncSessionMaker() as session:
            ctx = self.execution_context.context
            ctx["session"] = session
            ctx["errors"] = []
            ctx.update(self.loaders_factory(session))
            # query_str = ctx.get("query_str")
            try:
            # před spuštěním operace
                async with DB_SEMAPHORE:
                    # opensessions = list(session_monitor.keys())
                    # if opensessions:
                    #     print(f"\033[1;31mStarting another session\033[0m {id} {len(opensessions)}", flush=True)
                    # else :
                    #     print(f"\033[1;32mStarting first session\033[0m {id}", flush=True)
                    # if query_str:
                    #     print(f"Starting operation {id} with query:\n{query_str}", flush=True)

                    # session_monitor[id] = session
                
                    yield

            # po dokončení operace:
            except Exception as e:
                # sem spadnou neočekávané chyby
                error_description = {
                    "msg": f"Unexpected error during operation: {e}",
                    "code": "43b027da-d073-4fac-8881-3353609f2bcd",
                    "_input": {},
                }
                ctx["errors"].append(error_description)

                await session.rollback()
                # print(f"Finalizing session {id} with exception", e, flush=True)
                raise
            else:
                # sem se jde jen když NEBYLA výjimka
                if ctx["errors"]:
                    await session.rollback()
                else:
                    await session.commit()
                # print("Finalizing session", id, flush=True)
            finally:
                # volitelné: uklidit reference, ať někdo nepoužije zavřenou session
                
                # ctx.pop("session", None)
                # session_monitor.pop(id, None)
                # opensessions = list(session_monitor.keys())
                # if opensessions:
                #     print(f"\033[1;31mVAROVÁNÍ: ZŮSTALY OTEVŘENÉ SESSION: {len(opensessions)}\n{opensessions}\033[0m", flush=True)
                # else :
                #     print("\033[1;32mAll sessions closed properly.\033[0m", flush=True)
                pass
            
            
def SessionCommitExtensionFactory(*, session_maker_factory, loaders_factory, SessionCommitExtension=SessionCommitExtension):
    return SessionCommitExtension(
            session_maker_factory=session_maker_factory,
            loaders_factory=loaders_factory,
        )