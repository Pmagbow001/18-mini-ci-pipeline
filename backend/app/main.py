import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload
from .db import Session
from .models import Project, Pipeline, Run, Job
from .seed import STEPS, seed

DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    seed()
    yield

app = FastAPI(title="MiniCI", version="1.0.0", lifespan=lifespan)
cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", ",".join(DEFAULT_CORS_ORIGINS)).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

def iso(t):
    return t.isoformat() if t else None

def run_json(r):
    return {"id":r.id,"pipeline_id":r.pipeline_id,"fixture":r.fixture,"status":r.status,
            "triggered_at":iso(r.triggered_at),"started_at":iso(r.started_at),
            "finished_at":iso(r.finished_at),"failure_reason":r.failure_reason,
            "jobs":[{"id":j.id,"name":j.name,"step_order":j.step_order,"status":j.status,
                     "exit_code":j.exit_code,"logs":j.logs,"duration_ms":j.duration_ms,
                     "started_at":iso(j.started_at),"finished_at":iso(j.finished_at)} for j in r.jobs]}

def fetch_run(db, run_id):
    r = db.scalar(select(Run).options(selectinload(Run.jobs)).where(Run.id == run_id))
    if not r: raise HTTPException(404, "Run not found")
    return r

class Trigger(BaseModel):
    fixture: Literal["success", "failure"] = "success"

@app.get("/api/health")
def health():
    with Session() as db:
        db.execute(text("SELECT 1"))
    return {"status":"ok"}

@app.get("/api/projects")
def projects():
    with Session() as db:
        return [{"id":p.id,"name":p.name,"slug":p.slug,"description":p.description} for p in db.scalars(select(Project)).all()]

@app.get("/api/projects/{project_id}")
def project(project_id: str):
    with Session() as db:
        p=db.get(Project,project_id)
        if not p: raise HTTPException(404,"Project not found")
        return {"id":p.id,"name":p.name,"slug":p.slug,"description":p.description}

@app.get("/api/pipelines")
def pipelines():
    with Session() as db:
        return [{"id":p.id,"name":p.name,"project_id":p.project_id,"steps":STEPS} for p in db.scalars(select(Pipeline)).all()]

@app.get("/api/pipelines/{pipeline_id}")
def pipeline(pipeline_id: str):
    with Session() as db:
        p=db.get(Pipeline,pipeline_id)
        if not p: raise HTTPException(404,"Pipeline not found")
        return {"id":p.id,"name":p.name,"project_id":p.project_id,"steps":STEPS}

def create_run(db, pipeline_id, fixture):
    p=db.get(Pipeline,pipeline_id)
    if not p or not p.is_active: raise HTTPException(404,"Pipeline not found")
    if fixture not in ("success","failure"): raise HTTPException(422,"Invalid fixture")
    active=db.scalars(select(Run).where(Run.status.in_(["queued","running"])).limit(20)).all()
    if len(active)>=10: raise HTTPException(429,"Too many active runs")
    r=Run(pipeline_id=pipeline_id,fixture=fixture)
    r.jobs=[Job(step_order=i,name=s["name"],command_label=s["command"]) for i,s in enumerate(STEPS)]
    db.add(r); db.flush()
    return r.id

@app.post("/api/pipelines/{pipeline_id}/runs",status_code=201)
def trigger(pipeline_id: str, body: Trigger):
    with Session.begin() as db:
        rid=create_run(db,pipeline_id,body.fixture)
    return {"id":rid,"status":"queued"}

@app.get("/api/runs")
def runs(limit: int=Query(30,ge=1,le=100),status: str | None=None):
    with Session() as db:
        q=select(Run).options(selectinload(Run.jobs)).order_by(Run.triggered_at.desc()).limit(limit)
        if status: q=q.where(Run.status==status)
        return [run_json(r) for r in db.scalars(q).all()]

@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    with Session() as db: return run_json(fetch_run(db,run_id))

@app.get("/api/runs/{run_id}/logs")
def logs(run_id: str):
    with Session() as db:
        r=fetch_run(db,run_id)
        return [{"job_id":j.id,"name":j.name,"logs":j.logs} for j in r.jobs]

@app.post("/api/runs/{run_id}/cancel")
def cancel(run_id: str):
    with Session.begin() as db:
        r=fetch_run(db,run_id)
        if r.status=="queued":
            r.status="cancelled";r.finished_at=datetime.now(timezone.utc)
            for j in r.jobs: j.status="cancelled"
        elif r.status=="running":
            r.cancel_requested_at=datetime.now(timezone.utc)
        return {"id":r.id,"status":r.status,"cancel_requested":bool(r.cancel_requested_at)}

@app.post("/api/runs/{run_id}/rerun",status_code=201)
def rerun(run_id: str):
    with Session.begin() as db:
        old=fetch_run(db,run_id)
        if old.status in ("queued","running"): raise HTTPException(409,"Run still active")
        rid=create_run(db,old.pipeline_id,old.fixture)
    return {"id":rid,"status":"queued"}
