
from prometheus_client import Summary, Counter, Gauge, Histogram
import strawberry
import functools

@functools.cache
def createMonitor(prefix="Microservice"):
    return Monitor(prefix=prefix)

class Monitor:
    def __init__(self, prefix):
        self.REQUEST_TIME = Histogram(
            'gql_request_processing_seconds', 
            'Time spent processing GraphQL requests',
            namespace=prefix,
            buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1, 2, float("inf")],
            labelnames=["field"]
        )
        self.REQUEST_COUNTER = Counter(
            f'{prefix}:graphql_requests_total', 
            'Total number of GraphQL requests')
        self.IN_PROGRESS = Gauge(
            f'{prefix}:graphql_requests_in_progress', 
            'Number of GraphQL requests in progress')
        # self.TIMERS = {}
        # self.prefix = prefix

    # def __getitem__(self, index):
    #     result = self.TIMERS.get(index, None)
    #     if result is None:
    #         result = Summary(f"{self.prefix}:{index}", 'Time spent processing resolvers in query')
    #         self.TIMERS[index] = result
    #     return result

class PrometheusExtension(strawberry.extensions.SchemaExtension):
    def __init__(self, prefix):
        self.prefix = prefix
        self.monitor = Monitor(prefix)

    def on_request_start(self):
        # Increment request counter and in-progress gauge
        monitor = self.monitor
        monitor.REQUEST_COUNTER.inc()
        monitor.IN_PROGRESS.inc()

    def on_request_end(self):
        # Decrement in-progress gauge
        self.monitor.IN_PROGRESS.dec()

    async def resolve(self, _next, root, info, *args, **kwargs):
        # Measure the duration of field resolution
        field_path = info.path.as_list()
        str_field_path = ".".join((item for item in field_path if isinstance(item, str)))
        with self.monitor.REQUEST_TIME.labels(str_field_path).time():
            result = _next(root, info, *args, **kwargs)
            if info.is_awaitable(result):
                result = await result
        return result