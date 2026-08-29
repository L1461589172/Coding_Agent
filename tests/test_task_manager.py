import asyncio

from app.services.tasks import TaskManager


def test_immediate_shutdown_closes_pending_task():
    class UnusedRunner:
        async def run(self, task, events):
            raise AssertionError("The pending job should not start")

    async def scenario():
        manager = TaskManager(UnusedRunner())
        task = await manager.create("pending")
        await manager.close()
        assert manager.get(task.id).error.code == "SERVER_SHUTDOWN"
        assert manager.get_log(task.id).closed

    asyncio.run(scenario())


def test_success_branch_uses_injected_test_runner():
    class TestRunner:
        async def run(self, task, events):
            return "test-only result; not an agent implementation"

    async def scenario():
        manager = TaskManager(TestRunner())
        task = await manager.create("unit test")
        chunks = [chunk async for chunk in manager.get_log(task.id).stream()]
        assert manager.get(task.id).status == "COMPLETED"
        assert "task_completed" in chunks[-1]
        await manager.close()

    asyncio.run(scenario())
