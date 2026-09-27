import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.aggregate_analysis import resume_aggregate_jobs
from app.database import (init_db, migrate_storage, recoverable_aggregate_job_ids,
                          recoverable_file_ids, unhashed_file_ids)
from app.routes.files import router as files_router
from app.routes.guardrails import router as guardrails_router
from app.transcription import resume_files


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    migrate_storage()
    file_ids = recoverable_file_ids() + unhashed_file_ids()
    if file_ids:
        app.state.recovery_task = asyncio.create_task(asyncio.to_thread(resume_files, file_ids))
    aggregate_job_ids = recoverable_aggregate_job_ids()
    if aggregate_job_ids:
        app.state.aggregate_recovery_task = asyncio.create_task(
            asyncio.to_thread(resume_aggregate_jobs, aggregate_job_ids)
        )
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(files_router)
app.include_router(guardrails_router)


@app.get("/health")
def health():
    return {"status": "ok"}
