"""Async batching for English speech transcription."""

import asyncio
import os
from typing import Any

from loguru import logger

from .constants import ASR_BATCH_MAX, ASR_BATCH_WINDOW_S
from .schemas import AudioJob


job_store: dict[str, dict[str, Any]] = {}
audio_en_queue: asyncio.Queue[AudioJob] = asyncio.Queue()


async def audio_en_worker() -> None:
    from .models import transcribe_en_batch

    loop = asyncio.get_event_loop()
    while True:
        first_job = await audio_en_queue.get()
        batch = [first_job]
        deadline = loop.time() + ASR_BATCH_WINDOW_S
        while len(batch) < ASR_BATCH_MAX:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                batch.append(await asyncio.wait_for(audio_en_queue.get(), timeout=remaining))
            except asyncio.TimeoutError:
                break

        try:
            for job in batch:
                job_store[job.job_id]["status"] = "processing"
            transcripts = await loop.run_in_executor(
                None, transcribe_en_batch, [job.audio_path for job in batch]
            )
            for job, transcript in zip(batch, transcripts):
                if transcript.strip():
                    job_store[job.job_id].update(status="done", result=transcript)
                else:
                    job_store[job.job_id].update(
                        status="error",
                        error="Could not transcribe audio. Please speak clearly and try again.",
                    )
                job.done.set()
        except Exception as exc:
            logger.error(f"English ASR batch failed: {exc}")
            for job in batch:
                job_store[job.job_id].update(status="error", error=str(exc))
                job.done.set()
        finally:
            for job in batch:
                try:
                    os.unlink(job.audio_path)
                except OSError:
                    pass


_workers_started = False


def start_asr_workers() -> None:
    global _workers_started
    if _workers_started:
        return
    _workers_started = True
    for index in range(2):
        asyncio.create_task(audio_en_worker(), name=f"asr_en_worker_{index}")
    logger.info("English ASR workers started")
