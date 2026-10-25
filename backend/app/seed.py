from sqlalchemy import select
from .db import Base, engine, Session
from .models import Project, Pipeline
STEPS = [{"name": "Lint", "command": "npm run lint"}, {"name": "Test", "command": "npm run test -- --run"}, {"name": "Build", "command": "npm run build"}]

def seed():
    Base.metadata.create_all(engine)
    with Session.begin() as db:
        project = db.scalar(select(Project).where(Project.slug == "sample-typescript"))
        if project is None:
            project = Project(name="Sample TypeScript", slug="sample-typescript", description="Trusted local fixture")
            db.add(project)
            db.flush()
        if not db.scalar(select(Pipeline).where(Pipeline.project_id == project.id)):
            db.add(Pipeline(project_id=project.id, name="Default CI", steps_config=STEPS))

if __name__ == "__main__":
    seed()
