import torch
from sentence_transformers import SentenceTransformer
from elasticsearch import AsyncElasticsearch, helpers
from sqlalchemy import select, update
from app.db.session import AsyncSessionLocal
from app.db.models import ChapterChunk, Story, Chapter
from app.core.config import settings
from loguru import logger
from typing import List, Dict, Any, Optional
import numpy as np

class SearchService:
    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        # Embedding config
        self.model_name = model_name
        self.model = None
        
        # ES config
        auth = None
        if settings.ELASTICSEARCH_USER and settings.ELASTICSEARCH_PASSWORD:
            auth = (settings.ELASTICSEARCH_USER, settings.ELASTICSEARCH_PASSWORD)
            
        self.es = AsyncElasticsearch(
            settings.ELASTICSEARCH_URL,
            basic_auth=auth,
            verify_certs=False
        )
        self.index_name = settings.ELASTICSEARCH_INDEX
        self._index_verified = False

    def _load_model(self):
        if self.model is None:
            logger.info(f"Loading embedding model: {self.model_name}")
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self.model = SentenceTransformer(self.model_name, device=device)
            logger.info(f"Model loaded on {device}")

    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        self._load_model()
        embeddings = self.model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()

    async def create_index_if_not_exists(self):
        try:
            if not self._index_verified and not await self.es.indices.exists(index=self.index_name):
                logger.info(f"Creating Elasticsearch index: {self.index_name}")
                mappings = {
                    "mappings": {
                        "properties": {
                            "story_id": {"type": "integer"},
                            "chapter_id": {"type": "integer"},
                            "story_title": {"type": "text", "analyzer": "standard"},
                            "chapter_title": {"type": "text", "analyzer": "standard"},
                            "content": {"type": "text", "analyzer": "standard"},
                            "url": {"type": "keyword"},
                            "embedding": {
                                "type": "dense_vector",
                                "dims": 384,
                                "index": True,
                                "similarity": "cosine"
                            },
                            "created_at": {"type": "date"}
                        }
                    }
                }
                await self.es.indices.create(index=self.index_name, mappings=mappings["mappings"])
                logger.info(f"Successfully created index {self.index_name}")
            self._index_verified = True
        except Exception as e:
            logger.error(f"Error checking/creating ES index: {e}")
            self._index_verified = True

    async def index_chunks(self, chunks_data: List[Dict[str, Any]]):
        await self.create_index_if_not_exists()
        
        actions = [
            {
                "_index": self.index_name,
                "_id": f"{item['chapter_id']}_{idx}",
                "_source": item
            }
            for idx, item in enumerate(chunks_data)
        ]
        
        try:
            success, failed = await helpers.async_bulk(self.es, actions)
            logger.info(f"Indexed {success} chunks to Elasticsearch. Failed: {len(failed)}")
        except Exception as e:
            logger.error(f"Failed to bulk index to Elasticsearch: {e}")

    async def hybrid_search(self, query: str, limit: int = 5, story_id: int = None):
        """
        Performs a hybrid search using both text (BM25) and vector (kNN) search.
        ES 8.x automatically combines scores from both.
        """
        if not settings.ELASTICSEARCH_URL:
            logger.warning("Elasticsearch not configured, search unavailable")
            return []

        # 1. Generate embedding for query
        query_embedding = await self.generate_embeddings([query])
        embedding = query_embedding[0]
        
        # 2. Build standard ES 8.x hybrid query
        body = {
            "size": limit,
            "query": {
                "bool": {
                    "must": [
                        {
                            "bool": {
                                "should": [
                                    {
                                        "multi_match": {
                                            "query": query,
                                            "fields": ["content", "story_title^3", "chapter_title"],
                                            "type": "best_fields",
                                            "operator": "or"
                                        }
                                    },
                                    {
                                        "match_phrase": {
                                            "story_title": {
                                                "query": query,
                                                "boost": 10
                                            }
                                        }
                                    }
                                ],
                                "minimum_should_match": 1
                            }
                        }
                    ],
                    "filter": [{"term": {"story_id": story_id}}] if story_id else []
                }
            },
            "knn": {
                "field": "embedding",
                "query_vector": embedding,
                "k": limit,
                "num_candidates": 100,
                "filter": [{"term": {"story_id": story_id}}] if story_id else []
            }
        }
        
        try:
            response = await self.es.search(index=self.index_name, body=body)
            return response['hits']['hits']
        except Exception as e:
            logger.error(f"Elasticsearch search failed: {e}")
            return []

    async def vectorize_and_index_story(self, story_id: int, job_id: str = None):
        """
        Generates embeddings for all chunks of a story and indexes them into Elasticsearch.
        """
        async with AsyncSessionLocal() as session:
            try:
                # 1. DB: Find chunks without embeddings
                stmt = (
                    select(ChapterChunk)
                    .join(Chapter)
                    .where(
                        Chapter.story_id == story_id,
                        ChapterChunk.embedding.is_(None)
                    )
                )
                result = await session.execute(stmt)
                chunks = result.scalars().all()
                
                if not chunks:
                    logger.info(f"No chunks need vectorization for story {story_id}")
                    # Still might want to re-index if ES is empty, but for now skip
                    return []

                logger.info(f"Vectorizing {len(chunks)} chunks for story {story_id}")
                
                texts = [chunk.chunk_content for chunk in chunks]
                embeddings = await self.generate_embeddings(texts)
                
                for chunk, emb in zip(chunks, embeddings):
                    chunk.embedding = emb
                
                await session.commit()
                
                # 2. ES: Prepare data and index
                story_stmt = select(Story).where(Story.id == story_id)
                story_res = await session.execute(story_stmt)
                db_story = story_res.scalar_one()

                # Get chapter titles for better indexing
                chapter_ids = list(set(chunk.chapter_id for chunk in chunks))
                chap_stmt = select(Chapter).where(Chapter.id.in_(chapter_ids))
                chap_res = await session.execute(chap_stmt)
                chap_map = {c.id: c.title for c in chap_res.scalars().all()}

                es_data = []
                for chunk in chunks:
                    es_data.append({
                        "story_id": story_id,
                        "chapter_id": chunk.chapter_id,
                        "story_title": db_story.title,
                        "chapter_title": chap_map.get(chunk.chapter_id, "Chapter"),
                        "content": chunk.chunk_content,
                        "url": db_story.url,
                        "embedding": chunk.embedding,
                        "created_at": db_story.created_at.isoformat() if db_story.created_at else None
                    })
                
                if es_data:
                    await self.index_chunks(es_data)
                
                return es_data
            except Exception as e:
                logger.error(f"Failed to vectorize and index story {story_id}: {e}")
                raise e

    async def close(self):
        await self.es.close()
