from sqlalchemy import Column, Integer, Text, String, ForeignKey, ARRAY, DateTime
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.sql import func

class Base(DeclarativeBase):
    pass

class Story(Base):
    __tablename__ = "stories"
    
    id = Column(Integer, primary_key=True)
    title = Column(Text, nullable=False)
    author = Column(String)
    genres = Column(ARRAY(String))
    description = Column(Text)
    status = Column(String)
    url = Column(Text, unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    chapters = relationship("Chapter", back_populates="story", cascade="all, delete-orphan")

class Chapter(Base):
    __tablename__ = "chapters"
    
    id = Column(Integer, primary_key=True)
    story_id = Column(Integer, ForeignKey("stories.id", ondelete="CASCADE"))
    title = Column(Text, nullable=False)
    url = Column(Text, nullable=False)
    content = Column(Text)
    order = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    story = relationship("Story", back_populates="chapters")
    chunks = relationship("ChapterChunk", back_populates="chapter", cascade="all, delete-orphan")

class ChapterChunk(Base):
    __tablename__ = "chapter_chunks"
    
    id = Column(Integer, primary_key=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"))
    chunk_content = Column(Text, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    embedding = Column(Vector(384)) # Dimension for all-MiniLM-L6-v2
    
    chapter = relationship("Chapter", back_populates="chunks")

class Job(Base):
    __tablename__ = "jobs"
    
    id = Column(String, primary_key=True) # UUID or custom ID
    url = Column(Text, nullable=False)
    type = Column(String) # 'single' or 'batch'
    status = Column(String, default="pending") # pending, processing, completed, failed
    progress = Column(Integer, default=0) # percentage or count
    result_path = Column(Text) # Path to JSON if saved
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
