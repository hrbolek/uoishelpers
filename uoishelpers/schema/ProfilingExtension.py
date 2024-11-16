import time
import strawberry

class Counter:
    def __init__(self):
        self.accumulator = {}

    def count(self, strpath: str, duration: float):
        oldvalue = self.accumulator.get(strpath, {"count": 0, "sum": 0, "values": []})
        oldvalue["count"] += 1
        oldvalue["sum"] += duration
        oldvalue["values"].append(duration)
        self.accumulator[strpath] = oldvalue
        pass

    def result(self):
        return self.accumulator

class ProfilingExtension(strawberry.extensions.SchemaExtension):
    def on_execute(self):
        counter = Counter()
        self.execution_context.context["ProfilingExtension.counter"] = counter
        start_time = time.perf_counter()
        yield
        duration = time.perf_counter() - start_time
        counter.count("total", duration)

    async def resolve(self, _resolver, root, info: strawberry.types.Info, *args, **kwargs):
        field_path = info.path.as_list()  # Unique path to each field
        start_time = time.perf_counter()
        
        # Execute the resolver function
        result = _resolver(root, info, *args, **kwargs)
        if info.is_awaitable(result):
            result = await result
        
        # Measure duration after resolver finishes
        duration = time.perf_counter() - start_time
        
        # Store duration in profiling data
        strpath = ".".join((item for item in field_path if isinstance(item, str)))
        counter = self.execution_context.context["ProfilingExtension.counter"]
        counter.count(strpath, duration)
        return result
    
    def get_results(self):
        counter = self.execution_context.context["ProfilingExtension.counter"]
        return {"ProfilingExtension": counter.result()}
    

