from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

SERVER = "localhost"
DATABASE = "AIVideoAtlamaDB"

CONNECTION_STRING = (
    f"mssql+pyodbc://@{SERVER}/{DATABASE}"
    "?driver=ODBC+Driver+17+for+SQL+Server"
    "&trusted_connection=yes"
)

engine = create_engine(CONNECTION_STRING)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)