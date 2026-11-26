"""Short-lived owner-scoped research runs on the existing single preview instance."""

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class ResearchJob:
    owner: str
    prompt: str
    instructions: str
    conversation: str
    task: asyncio.Task | None = None
    activity: str = "Starting the assignment"
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    revision: int = 0
    draft: str = ""
    draft_basis: dict = field(default_factory=dict)
    steps: list = field(default_factory=list)
    result: dict | None = None
    touched: float = field(default_factory=time.monotonic)


class ResearchJobs:
    def __init__(self):
        self.jobs = {}

    def prune(self):
        completed = [k for k, job in self.jobs.items() if job.result is not None]
        for key in completed:
            if time.monotonic() - self.jobs[key].touched > 900 or len(self.jobs) >= 24:
                del self.jobs[key]

    def get(self, key, owner):
        self.prune()
        job = self.jobs.get(key)
        return job if job and job.owner == owner else None

    def start(self, key, owner, prompt, instructions, conversation, stream):
        self.prune()
        job = ResearchJob(owner, prompt, instructions, conversation)
        self.jobs[key] = job

        async def run():
            try:
                async for event in stream():
                    if event["type"] == "draft":
                        job.draft = event["text"]
                        job.draft_basis = event.get("basis", {})
                        job.activity = "Writing the answer"
                    elif event["type"] == "activity":
                        if event.get("clear_draft"):
                            job.draft = ""
                            job.draft_basis = {}
                        job.activity = event["text"]
                        if "step" in event:
                            job.steps.append(event["step"])
                    else:
                        job.result = event
                    job.revision += 1
                    job.changed.set()
                    job.changed = asyncio.Event()
            except asyncio.CancelledError:
                job.result = {"type": "error", "text": "Assignment stopped."}
            except Exception:
                # Request content, credentials and provider payloads must stay out of logs.
                job.result = {"type": "error", "text": "The research run was interrupted. Your earlier work is available."}
            finally:
                job.draft = ""
                job.draft_basis = {}
                job.changed.set()
                job.touched = time.monotonic()
                if job.result is None:
                    job.result = {"type": "error", "text": "The research run ended before an answer was available."}
        job.task = asyncio.create_task(run())
        return key

    async def close(self):
        pending = [job.task for job in self.jobs.values() if job.task and not job.task.done()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
