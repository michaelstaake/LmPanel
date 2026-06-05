import asyncio
import itertools


class QueueManager:
    def __init__(self) -> None:
        self._counter = itertools.count()
        self._queue: asyncio.PriorityQueue[tuple[int, int, dict]] = asyncio.PriorityQueue()

    async def put(self, priority: int, payload: dict) -> None:
        await self._queue.put((priority, next(self._counter), payload))

    async def get(self) -> dict:
        _, _, payload = await self._queue.get()
        return payload

    def qsize(self) -> int:
        return self._queue.qsize()
