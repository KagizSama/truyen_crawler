# 📖 Truyen Crawler — Project Log

> **Cập nhật lần cuối**: 2026-03-02
>
> Tài liệu này ghi lại lịch sử phát triển, kiến trúc, và các quyết định kỹ thuật quan trọng của dự án.

---

## 🏗️ Tổng quan kiến trúc

**Truyen Crawler** là ứng dụng web crawl tiểu thuyết từ TruyenFull, lưu trữ vào PostgreSQL, index vào Elasticsearch, và cung cấp chatbot AI hỗ trợ tìm kiếm/tóm tắt truyện.

### Tech Stack

| Thành phần | Công nghệ |
|------------|-----------|
| **Backend** | FastAPI + Uvicorn |
| **Database** | PostgreSQL + SQLAlchemy (async) + pgvector |
| **Search Engine** | Elasticsearch 8.12 (hybrid: full-text + dense vector) |
| **Embedding** | SentenceTransformers (`paraphrase-multilingual-MiniLM-L12-v2`, 384-dim) |
| **LLM** | Google Gemini (`gemini-2.5-flash-lite`) via `google-genai` SDK |
| **Agent Framework** | LangGraph + LangChain |
| **State Management** | Redis (LangGraph checkpointer) |
| **Frontend** | Vanilla HTML/CSS/JS (chat UI) |
| **Package Manager** | Poetry |
| **Containerization** | Docker Compose (Elasticsearch + Redis) |

### Sơ đồ luồng

```
User (Chat UI) → FastAPI → AgentService
                              ├── USE_LANGGRAPH=true  → LangGraphAgent
                              │                           ├── search_library_tool → SearchService → Elasticsearch
                              │                           ├── crawl_story_tool → CrawlerService → PostgreSQL
                              │                           └── Gemini LLM (summarize/answer)
                              └── USE_LANGGRAPH=false → Legacy Gemini Agent (direct API)
```

---

## 📁 Cấu trúc thư mục

```
truyen_crawler/
├── app/
│   ├── main.py                    # FastAPI app, routing
│   ├── api/v1/endpoints/
│   │   ├── crawler.py             # /api/v1/crawl endpoints
│   │   ├── search.py              # /api/v1/search endpoint
│   │   └── agent.py               # /api/v1/agent/chat endpoint
│   ├── core/
│   │   ├── config.py              # Pydantic Settings (env vars)
│   │   └── exceptions.py          # Custom exceptions
│   ├── db/
│   │   ├── models.py              # SQLAlchemy models (Story, Chapter, ChapterChunk, Job)
│   │   ├── session.py             # AsyncSessionLocal
│   │   ├── backfill.py            # Reset + re-index data vào Elasticsearch
│   │   └── add_embedding_col.py   # One-time migration: thêm cột embedding vào chapter_chunks
│   ├── services/
│   │   ├── agent_service.py       # AgentService — router giữa LangGraph vs Legacy
│   │   ├── langgraph_agent.py     # LangGraphAgent — graph: agent → reflect → retry
│   │   ├── langgraph_tools.py     # LangChain tools cho LangGraph (search, crawl)
│   │   ├── tools.py               # Tool functions cho Legacy agent (search, crawl)
│   │   ├── crawler.py             # CrawlerService — crawl truyện + auto-index
│   │   ├── search_service.py      # SearchService — embedding + Elasticsearch hybrid search
│   │   └── processor.py           # Text processor (chunking)
│   ├── schemas/
│   │   ├── story.py               # Pydantic models cho Story data
│   │   └── agent.py               # ChatResponse, SourceNode schemas
│   ├── utils/
│   │   └── redis_checkpointer.py  # Redis-based checkpointer cho LangGraph
│   └── static/                    # Chat UI (HTML/CSS/JS)
├── tests/
│   ├── test_agent_service.py
│   ├── test_api.py
│   ├── test_langgraph_agent.py
│   └── test_search_service.py
├── data/                          # Crawled JSON data (gitignored)
├── runner.py                      # CLI: crawl single story
├── batch_runner.py                # CLI: crawl batch stories
├── docker-compose.yml             # Elasticsearch + Redis
├── pyproject.toml                 # Python dependencies (Poetry)
└── .env                           # Environment variables
```

---

## 📅 Timeline phát triển

### Phase 1: Elasticsearch Integration (19/01 – 27/01/2026)

**Conversation**: *Elasticsearch Integration and Optimization*

**Mục tiêu**: Tích hợp Elasticsearch vào hệ thống crawl truyện, hỗ trợ full-text search và dense vector search (hybrid).

**Thay đổi chính**:
- Tạo `SearchService` — unified service cho embedding + Elasticsearch
- Setup Elasticsearch 8.12 via Docker Compose
- Tạo DB models: `Story`, `Chapter`, `ChapterChunk` (với cột `embedding` vector(384))
- Implement hybrid search: kết hợp BM25 full-text + dense vector cosine similarity
- Backfill script (`backfill.py`) để reset và re-index data
- Sử dụng `SentenceTransformers` model `paraphrase-multilingual-MiniLM-L12-v2` cho embedding

**Ghi chú kỹ thuật**:
- Elasticsearch client phải dùng version < 9.0.0 để tương thích
- Embedding dimension: 384 (khớp với model MiniLM)
- Chunk size: xử lý bởi `processor.py`

---

### Phase 2: Search Service Refactoring (28/01/2026)

**Conversation**: *Elasticsearch Integration Optimization*

**Mục tiêu**: Gộp embedding service + Elasticsearch service thành một `SearchService` thống nhất.

**Thay đổi chính**:
- Merge API endpoints thành single `/api/v1/search`
- Tạo unified `backfill.py` xử lý cả reset và re-index
- Cập nhật crawler tự động index sau khi crawl (`auto-indexing`)
- Cleanup file thừa từ phase 1

**Ghi chú kỹ thuật**:
- Auto-indexing chạy synchronous sau `save_story_to_db()` — đơn giản hơn background task
- Xử lý lỗi: nếu Elasticsearch down, crawl vẫn thành công, chỉ index thất bại

---

### Phase 3: Google GenAI Migration (02/02 – 05/02/2026)

**Conversation**: *Migrating LLM Provider*

**Mục tiêu**: Migrate từ deprecated `google.generativeai` (v0.8.6) sang `google.genai` (v0.4.0).

**Thay đổi chính**:
- Dependency: `google-generativeai` → `google-genai`
- Import: `import google.generativeai as genai` → `from google import genai`
- Client: `genai.configure()` global → `genai.Client()` instance
- API calls: `model.generate_content()` → `client.models.generate_content()`
- Tool declarations: Auto-inferred → explicit `FunctionDeclaration` schema
- Message format: dict → `types.Content` objects
- Function response role: `"function"` → `"tool"`

**Ghi chú kỹ thuật**:
- `GenerateContentConfig` chứa tools + system_instruction (request-level, không phải model-level)
- `Part.from_function_response()` thay thế `genai.protos.Part(function_response=...)`
- Model hiện tại: `gemini-2.5-flash-lite`

---

### Phase 4: Chatbot Intelligence Improvements (05/02/2026)

**Conversation**: *Improving Chatbot Intelligence*

**Mục tiêu**: Nâng cao khả năng hiểu ý người dùng và chất lượng tóm tắt.

**Thay đổi chính**:
- Cải thiện query understanding (query rewriting dựa trên chat history)
- Tăng depth retrieval từ Elasticsearch (nhiều chunks hơn)
- Tối ưu system prompt cho LLM:
  - Hướng dẫn chi tiết cách tóm tắt toàn bộ bộ truyện vs. tóm tắt phần cụ thể
  - Quy tắc trích dẫn nguồn
  - Xử lý follow-up questions (dùng context từ history)
  - Cảnh báo khi search trả về quá ít kết quả
- Phrase matching với boost trong Elasticsearch

---

### Phase 5: LangGraph Agent Integration (05/02 – 09/02/2026)

**Conversations**: *Debugging LangGraph Agent*, *Reviewing RAG and LangGraph Pipeline*

**Mục tiêu**: Thay thế legacy Gemini agent bằng LangGraph agent với state management và reflection.

**Thay đổi chính**:
- Tạo `LangGraphAgent` với graph: `agent` → `reflect` → (retry nếu BAD)
- Tạo `langgraph_tools.py` — LangChain-compatible tools
- Tạo `RedisCheckpointer` cho persistent state across requests
- Cấu hình `USE_LANGGRAPH=true` trong settings
- `AgentService` router giữa LangGraph và Legacy mode
- Thêm `ENABLE_REFLECTION=true` cho self-correction loop

**Graph flow**:
```
agent_node → reflect_node → [GOOD] → END
                           → [BAD]  → agent_node (retry, max 2 lần)
```

**Ghi chú kỹ thuật**:
- `AgentState` chứa: `messages`, `session_id`, `retry_count`, `critique`
- Redis TTL: 24h cho conversation state
- `MAX_RECURSION_LIMIT=50` để tránh infinite loop
- LangGraph dùng `langchain-google-genai` adapter để gọi Gemini
- Reflection prompt đánh giá chất lượng câu trả lời (GOOD/BAD + critique)

---

### Phase 6: LLM Request Optimization (14/02/2026)

**Mục tiêu**: Giảm số lượng LLM API calls lãng phí để tiết kiệm quota Google.

**Vấn đề trước đó**: Mỗi query đơn giản ("Chào bạn") có thể tốn 2–4 LLM calls (agent + reflect + retry + reflect lại).

**4 tối ưu đã áp dụng**:

| # | Tối ưu | File | Tiết kiệm |
|---|--------|------|-----------|
| 1 | **Simple-query shortcut** — chào hỏi/cảm ơn trả lời ngay, 0 LLM calls | `langgraph_agent.py` | 100% cho greetings |
| 2 | **Smart reflection bypass** — chỉ reflect khi agent đã dùng tool | `langgraph_agent.py` | 1–3 calls/query đơn giản |
| 3 | **History trimming** — giới hạn 10 messages gần nhất | `langgraph_agent.py` | ~60% tokens |
| 4 | **Rule-based query rewrite** — chỉ LLM rewrite khi query mơ hồ | `agent_service.py` | 1 call/query rõ ràng |

**Chi tiết kỹ thuật**:
- `SIMPLE_RESPONSES`: 4 categories (greetings, thanks, goodbye, ok), chỉ match query < 30 ký tự
- `MAX_HISTORY_MESSAGES = 10`: trim khi load previous state
- `_AMBIGUOUS_INDICATORS`: 16 từ mơ hồ cần LLM rewrite ("nó", "bộ đó", "tiếp"...)
- Reflection chỉ trigger khi có `ToolMessage` trong messages

---

### Phase 7: Rate Limit Error Handling (24/02/2026)

**Mục tiêu**: Xử lý graceful khi Gemini API hết quota (429 ResourceExhausted), tránh vòng lặp lãng phí LLM calls.

**Vấn đề trước đó**: Khi `gemini-2.5-flash` free tier hết quota (5 req/min):
- Agent bịa đặt thông tin thay vì trả lỗi rõ ràng
- Reflection vẫn chạy (thêm 1 LLM call) → đánh giá BAD
- Retry chạy ngay (thêm 1+ LLM call) → hết quota tiếp → vòng lặp xấu
- Kết quả: 4–6 LLM calls lãng phí, user nhận câu trả lời bịa đặt

**3 thay đổi trong `langgraph_agent.py`**:

| # | Thay đổi | Hiệu quả |
|---|----------|-----------|
| 1 | **Bắt lỗi 429 trong `_agent_node`** — trả thông báo "hệ thống quá tải" thay vì bịa đặt | User biết lỗi thật, không bị mislead |
| 2 | **Skip reflection khi `quota_exhausted=True`** — `_should_continue` đi thẳng END | Tiết kiệm 1–3 LLM calls |
| 3 | **Thêm delay 15s trước retry** — `_should_retry` sleep để chờ quota refresh | Retry có cơ hội thành công |

**Ghi chú kỹ thuật**:
- Thêm field `quota_exhausted: bool` vào `AgentState`
- Lỗi được bắt bằng string matching (`"ResourceExhausted"` hoặc `"429"` trong exception message)
- Graph-level catch trong `chat()` vẫn giữ làm fallback

---

### Phase 8: Browse Library Tool & System Prompt (24/02/2026)

**Mục tiêu**: Cho phép agent duyệt thư viện metadata (thể loại, truyện, recommend) thay vì chỉ tìm kiếm nội dung.

**Vấn đề trước đó**: Agent chỉ có `search_library` (tìm content chunks trong ES). Khi user hỏi "có thể loại gì?", "recommend truyện", "truyện tiên hiệp" → agent nói "tôi không có khả năng" vì không có tool query metadata.

**Thay đổi chính**:

| File | Thay đổi |
|------|----------|
| `langgraph_tools.py` | Thêm tool `browse_library` với 3 actions: `list_genres`, `list_stories`, `random_recommend` |
| `langgraph_agent.py` | Cập nhật system prompt: thêm hướng dẫn `browse_library`, quy tắc "luôn thử tool trước" |

**Tool `browse_library`**:

| Action | Input | Output |
|--------|-------|--------|
| `list_genres` | — | 23 genres + số truyện mỗi genre |
| `list_stories` | `genre` (optional) | Truyện theo genre: title, author, status, description |
| `random_recommend` | `genre` (optional) | 5 truyện ngẫu nhiên (có thể filter genre) |

**Ghi chú kỹ thuật**:
- Query trực tiếp PostgreSQL (`stories` table) — 0 LLM calls, 0 embedding
- Dùng `Story.genres.any(genre)` cho PostgreSQL ARRAY filter
- `LANGGRAPH_TOOLS` giờ có 3 tools: `search_library`, `browse_library`, `crawl_story`
- System prompt thêm section "KHI NÀO DÙNG TOOL NÀO" để hướng dẫn agent routing
- **Async migration**: `graph.invoke()` → `await graph.ainvoke()`, `_agent_node`/`_reflect_node`/`_should_retry` → `async def` với `ainvoke()`. Fix event loop conflict khi `browse_library` (async SQLAlchemy) chạy từ sync graph context.

---

### Phase 9: Markdown Rendering cho Chat UI (01/03/2026)

**Mục tiêu**: Hiển thị câu trả lời của bot dưới dạng Markdown (headings, lists, bold, links…) thay vì plain-text/HTML thủ công.

**Vấn đề trước đó**: Bot trả về text có format Markdown nhưng UI chỉ thay `\n` → `<br>` và auto-link URL bằng regex — kết quả mất hết heading, list, bold.

**Thay đổi chính**:

| File | Thay đổi |
|------|----------|
| `index.html` | Import thư viện [`md-block`](https://md-block.verou.me/) (web component) via CDN, bump cache version `v6` → `v7` |
| `script.js` | Thay logic `text.replace(/\n/g, '<br>')` + URL regex → tạo `<md-block>` element, dùng `outerHTML` để render Markdown natively |
| `script.js` | Fix `toggleSources()` — sửa logic toggle arrow `>` ↔ `v` bị lỗi khi text chứa ký tự `>`, thêm debug log |
| `style.css` | Thêm `md-block ul { margin-left: 1rem }` — fix bullet list bị sát lề trái |
| `style.css` | Thêm `.sources-list.hidden { display: none }` — class hidden không hoạt động trước đó |
| `style.css` | Thêm `cursor: pointer`, `transition`, hover effect cho `.toggle-sources` button |

**Ghi chú kỹ thuật**:
- `md-block` là web component, tự parse Markdown → HTML bên trong shadow DOM
- CDN: `https://md-block.verou.me/md-block.js` (loaded as ES module)
- Không cần thêm dependency vào `package.json` — chỉ dùng CDN
- Cả user message lẫn bot message đều đi qua `<md-block>`, nhưng user message thường plain text nên không ảnh hưởng

---

### Phase 10: Story Info Query Tool (02/03/2026)

**Mục tiêu**: Cho phép agent trả lời câu hỏi về thông tin cụ thể của một bộ truyện (tác giả, số chương, URL, trạng thái...) bằng cách query trực tiếp database.

**Vấn đề trước đó**: Agent đã có `browse_library` tool nhưng chỉ hỗ trợ `list_genres`, `list_stories`, `random_recommend`. Khi user hỏi "tác giả truyện X là ai?", "truyện X có bao nhiêu chương?", "URL truyện X" → agent không có action phù hợp → trả lời sai hoặc nói "không biết".

**Thay đổi chính**:

| File | Thay đổi |
|------|----------|
| `langgraph_tools.py` | Thêm field `title` vào `BrowseLibraryInput`, thêm action `get_story_info` |
| `langgraph_agent.py` | Cập nhật system prompt: thêm rule #5 cho `get_story_info` |

**Action `get_story_info`**:

| Input | Output |
|-------|--------|
| `title`: tên truyện (fuzzy match ILIKE) | `title`, `author`, `genres`, `status`, `url`, `description`, `chapter_count`, `created_at` |

**Ghi chú kỹ thuật**:
- Chapter count sử dụng subquery COUNT + LEFT JOIN — trả 0 nếu chưa có chapters
- Fuzzy match bằng `ILIKE '%title%'` — tìm cả partial match
- Limit 10 kết quả trả về
- Nếu không tìm thấy → gợi ý dùng `search_library` hoặc `crawl_story`

**Fix Gemini 400 "function call turn" error**:

| # | Fix | File |
|---|-----|------|
| 1 | **Sanitize history** — loại bỏ `ToolMessage` và `AIMessage(tool_calls)` khỏi history cũ trước khi gửi Gemini | `langgraph_agent.py` |
| 2 | **Error fallback** — bắt lỗi 400 "Invalid argument" / "function call turn", auto-reset session corrupted | `langgraph_agent.py` |

**Nguyên nhân**: Gemini yêu cầu function call phải nằm ngay sau user turn hoặc function response turn. Khi load history từ Redis, tool call/response cũ vi phạm quy tắc ordering → Gemini reject 400.

---

## ⚙️ Cấu hình quan trọng

### Environment Variables (`.env`)

| Biến | Mô tả | Default |
|------|--------|---------|
| `APP_DATABASE_URL` | PostgreSQL connection string | — |
| `APP_GEMINI_API_KEY` | Google AI API key | — |
| `APP_GEMINI_MODEL` | Model name | `gemini-2.5-flash-lite` |
| `APP_ELASTICSEARCH_URL` | Elasticsearch URL | `http://localhost:9200` |
| `APP_REDIS_URL` | Redis URL | `redis://localhost:6379` |
| `APP_USE_LANGGRAPH` | Bật LangGraph agent | `true` |
| `APP_ENABLE_REFLECTION` | Bật reflection loop | `true` |
| `APP_BASE_URL` | URL gốc TruyenFull | `https://truyenfull.vision` |

> **Lưu ý**: Tất cả biến đều có prefix `APP_` (do `env_prefix="APP_"` trong config).

### Chạy dự án

```bash
# 1. Start services
docker compose up -d          # Elasticsearch + Redis

# 2. Install dependencies
poetry install

# 3. Start app
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 4. (Optional) Backfill data vào Elasticsearch
poetry run python -m app.db.backfill

# 5. (Optional) Crawl single story
poetry run python runner.py <story_url>
```

---

## 🔧 Ghi chú kỹ thuật & Gotchas

1. **Embedding model load chậm lần đầu** — `SentenceTransformers` tải model ~8s lần đầu, sau đó cache trên GPU (cuda).

2. **Elasticsearch version < 9.0.0** — Package `elasticsearch` phải pin dưới 9.0 vì breaking changes.

3. **`google-genai` ≥ 1.x bắt buộc** — Đã migrate từ `google-generativeai` sang `google-genai`. Version ≥ 1.0 cần thiết cho `langchain-google-genai` 2.x (hỗ trợ `max_retries`).

4. **LangGraph reflection** — Reflection CHỈ chạy khi agent đã dùng tool (search/crawl). Câu chào hỏi skip reflection. Nếu BAD, retry tối đa 2 lần.

5. **Auto-indexing sau crawl** — `CrawlerService.crawl_story()` tự động index sau khi lưu DB. Nếu ES down, crawl vẫn thành công.

6. **`add_embedding_col.py`** — Script migration một lần, chỉ chạy khi setup DB lần đầu.

7. **Redis TTL 24h** — Conversation state hết hạn sau 24h.

8. **Dual agent mode** — `USE_LANGGRAPH=true` (LangGraph) hoặc `false` (Legacy Gemini fallback).

9. **Simple-query shortcut** — Queries < 30 ký tự matching chào hỏi bypass LLM. Sửa `SIMPLE_RESPONSES` trong `langgraph_agent.py` để thêm pattern.

10. **Query rewrite chỉ khi mơ hồ** — Legacy mode chỉ gọi LLM rewrite khi có đại từ. Xem `_AMBIGUOUS_INDICATORS` trong `agent_service.py`.

11. **History trimming** — `MAX_HISTORY_MESSAGES = 10`. Conversation dài hơn bị trim để giảm tokens.

12. **`google-genai` version** — `langchain-google-genai==2.1.12` cần `google-genai>=1.0` vì nó truyền `max_retries` vào `generate_content()`. Version 0.4.0 sẽ lỗi `unexpected keyword argument 'max_retries'`.

13. **`md-block` CDN dependency** — Chat UI phụ thuộc CDN `md-block.verou.me` để render Markdown. Nếu CDN down, bot responses sẽ hiện raw text. Cân nhắc self-host nếu cần offline.

---

## 📊 Database Schema

```
stories
├── id (PK)
├── title, author, genres[], description, status, url (unique)
└── created_at

chapters
├── id (PK)
├── story_id (FK → stories.id, CASCADE)
├── title, url, content, order
└── created_at

chapter_chunks
├── id (PK)
├── chapter_id (FK → chapters.id, CASCADE)
├── chunk_content, chunk_index
└── embedding vector(384)  -- pgvector

jobs
├── id (PK, UUID)
├── url, type (single/batch), status, progress, result_path, error
└── created_at, updated_at
```

---

## 🗑️ File đã cleanup (14/02/2026)

Các file debug/test/demo tạm đã bị xóa:

| File | Lý do xóa |
|------|-----------|
| `demo_langgraph.py` | Demo script, không dùng nữa |
| `dry_run_rag.py` | Test RAG pipeline, đã verify xong |
| `dry_run.log` | Log file tạm |
| `list_models.py` | Dùng API deprecated |
| `reproduce_issue.py` | Bug đã fix |
| `verify_langgraph.py` | Migration đã hoàn thành |
| `test_chatbot_improvements.py` | Test nằm ngoài `tests/` |
