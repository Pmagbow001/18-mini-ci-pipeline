import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

URL = os.getenv("DATABASE_URL", "postgresql+psycopg://minici:localdev@localhost:5432/minici")
engine = create_engine(URL, pool_pre_ping=True)
Session = sessionmaker(bind=engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass
