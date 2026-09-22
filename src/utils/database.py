"""
SQLite tracking for generated / uploaded Shorts.

The database is the rich local record. `progress.json` (see progress_store.py)
is the small, git-committable file that survives across GitHub Actions runs.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from .logger import get_logger

logger = get_logger(__name__)
Base = declarative_base()


class ShortRecord(Base):
    """One generated Short."""
    __tablename__ = "shorts"

    id = Column(Integer, primary_key=True)
    topic_id = Column(String(100), index=True)
    serial = Column(Integer, index=True)          # global running number
    title = Column(String(500))
    category = Column(String(100))
    status = Column(String(20), default="pending")  # pending|generated|uploaded|failed
    script_path = Column(String(500))
    audio_path = Column(String(500))
    video_path = Column(String(500))
    thumbnail_path = Column(String(500))
    youtube_id = Column(String(50))
    youtube_url = Column(String(200))
    duration = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)
    uploaded_at = Column(DateTime)
    error = Column(Text)


class Database:
    """Tracking store for Shorts generation."""

    def __init__(self, db_path: str = "data/shorts_tracker.db"):
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(f"sqlite:///{db_path}", echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)
        logger.info(f"Database ready: {db_path}")

    def get_session(self) -> Session:
        return self.SessionLocal()

    def create_record(self, topic_id: str, serial: int, title: str, category: str) -> None:
        with self.get_session() as session:
            existing = session.query(ShortRecord).filter_by(topic_id=topic_id).first()
            if existing:
                existing.serial = serial
                existing.status = "pending"
                existing.error = None
                session.commit()
                return
            session.add(ShortRecord(
                topic_id=topic_id, serial=serial, title=title,
                category=category, status="pending",
            ))
            session.commit()

    def update(self, topic_id: str, status: str = None, **fields) -> None:
        with self.get_session() as session:
            record = session.query(ShortRecord).filter_by(topic_id=topic_id).first()
            if not record:
                return
            if status:
                record.status = status
                if status == "uploaded":
                    record.uploaded_at = datetime.utcnow()
            for key, value in fields.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            session.commit()

    def used_topic_ids(self) -> List[str]:
        with self.get_session() as session:
            rows = session.query(ShortRecord.topic_id).filter(
                ShortRecord.status.in_(["generated", "uploaded"])
            ).all()
            return [r[0] for r in rows]

    def get_progress(self) -> Dict[str, Any]:
        with self.get_session() as session:
            return {
                "total": session.query(ShortRecord).count(),
                "uploaded": session.query(ShortRecord).filter_by(status="uploaded").count(),
                "generated": session.query(ShortRecord).filter_by(status="generated").count(),
                "failed": session.query(ShortRecord).filter_by(status="failed").count(),
            }

    def last_serial(self) -> int:
        with self.get_session() as session:
            row = session.query(ShortRecord).order_by(ShortRecord.serial.desc()).first()
            return row.serial if row and row.serial else 0
