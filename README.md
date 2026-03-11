# 📚 Novel AI — Hệ thống RAG hỏi đáp truyện tiểu thuyết

Hệ thống full-stack sử dụng **RAG (Retrieval-Augmented Generation)** để crawl, lưu trữ và hỏi đáp về nội dung truyện tiểu thuyết từ TruyenFull. Người dùng có thể chat với AI để hỏi về nội dung, tìm kiếm truyện, và duyệt thư viện.

## 🏗️ Kiến trúc hệ thống

```
┌─────────────┐     ┌──────────────────────────────────────────────┐
│  Frontend    │     │  Backend (FastAPI)                            │
│  React/Vite  │◄───►│  ┌─────────┐ ┌───────────┐ ┌─────────────┐  │
│  Port: 5173  │     │  │ Crawler │ │ LangGraph │ │ Search      │  │
└─────────────┘     │  │ Service │ │ Agent     │ │ Service     │  │
                    │  └────┬────┘ └─────┬─────┘ └──────┬──────┘  │
                    └───────┼───────────┼──────────────┼──────────┘
                            │           │              │
              ┌─────────────┼───────────┼──────────────┼──────────┐
              │             ▼           ▼              ▼          │
              │  ┌──────────────┐ ┌──────────┐ ┌──────────────┐   │
              │  │ PostgreSQL   │ │  Redis   │ │Elasticsearch │   │
              │  │ (Neon Cloud) │ │ (Docker) │ │  (Docker)    │   │
              │  └──────────────┘ └──────────┘ └──────────────┘   │
              └───────────────────────────────────────────────────┘
```

| Thành phần       | Công nghệ                                  |
| ---------------- | ------------------------------------------- |
| Frontend         | React 18, Vite, TailwindCSS                 |
| Backend          | FastAPI, Python 3.12+                       |
| AI Agent         | LangGraph, LangChain, Gemini API            |
| Tìm kiếm         | Elasticsearch 8.12 (full-text + vector)     |
| Cache            | Redis (lưu session LangGraph)               |
| Database         | PostgreSQL (Neon Cloud) + pgvector          |
| Embedding        | sentence-transformers (local)               |
| Auth             | JWT (email/password + Google OAuth)         |

---

## ⚙️ Yêu cầu hệ thống

- **Python** >= 3.12
- **Node.js** >= 18
- **Docker** & **Docker Compose**
- **Poetry** (quản lý dependencies Python)

---

## 🚀 Cài đặt & Chạy

### 1. Clone project

```bash
git clone <repo-url>
cd Novel_AI
```

### 2. Cấu hình Environment

Tạo file `.env` ở thư mục gốc:

```env
# URL nguồn crawl
APP_BASE_URL=https://truyenfull.vision
APP_CONCURRENT_REQUESTS=5
APP_BATCH_SIZE=15
APP_CHAPTER_DELAY=3
APP_RETRIES=3
APP_RETRY_BACKOFF=1.5
APP_SAVE_TO_JSON=false

# Database (PostgreSQL)
APP_DATABASE_URL="postgresql+asyncpg://<user>:<password>@<host>/<dbname>"

# Gemini API (cho AI Agent)
APP_GEMINI_API_KEY=<your-gemini-api-key>
APP_GEMINI_MODEL=gemini-2.5-flash

# JWT Secret
APP_JWT_SECRET_KEY=<random-secret-key>
```

### 3. Khởi động Docker (Elasticsearch + Redis)

```bash
docker-compose up -d
```

Kiểm tra containers đang chạy:

```bash
docker-compose ps
```

- **Elasticsearch**: http://localhost:9200
- **Redis**: localhost:6379

### 4. Cài đặt Backend

```bash
cd backend
poetry install
```

Chạy backend server:

```bash
poetry run uvicorn app.main:app --reload
```

Backend sẽ chạy tại: http://localhost:8000

### 5. Cài đặt Frontend

```bash
cd frontend
npm install
```

Chạy frontend dev server:

```bash
npm run dev
```

Frontend sẽ chạy tại: http://localhost:5173

---

## 📖 Hướng dẫn sử dụng Web

### Đăng ký & Đăng nhập

1. Truy cập http://localhost:5173
2. Nhấn **Đăng ký** để tạo tài khoản mới (email + mật khẩu)
3. Sau khi đăng ký, đăng nhập để vào hệ thống
4. Hỗ trợ đăng nhập bằng **Google OAuth** (nếu đã cấu hình)

### 💬 Chat với AI (Trang Chat)

Đây là tính năng chính của hệ thống RAG:

1. Sau khi đăng nhập, vào trang **Chat**
2. Tạo **phiên chat mới** hoặc chọn phiên chat cũ từ sidebar
3. Nhập câu hỏi về truyện, ví dụ:
   - *"Tóm tắt nội dung truyện Đấu Phá Thương Khung"*
   - *"Nhân vật chính trong truyện Thần Đạo Đan Tôn là ai?"*
   - *"Có truyện nào thuộc thể loại tiên hiệp không?"*
   - *"So sánh 2 truyện Đấu La Đại Lục và Đấu Phá Thương Khung"*
4. AI Agent sẽ tự động:
   - Phân tích câu hỏi
   - Tìm kiếm nội dung liên quan trong Elasticsearch
   - Truy vấn database để lấy metadata
   - Tổng hợp và trả lời bằng Gemini AI
5. Lịch sử chat được lưu lại, có thể xem lại bất cứ lúc nào

### 📚 Thư viện truyện (Trang Library)

1. Vào trang **Library** để duyệt toàn bộ truyện đã crawl
2. Tìm kiếm theo **tên truyện**, **tác giả**, hoặc **thể loại**
3. Xem thông tin chi tiết: tiêu đề, tác giả, thể loại, mô tả, trạng thái

### 🔧 Quản trị (Trang Admin — chỉ dành cho Admin)

1. Vào trang **Admin** (yêu cầu quyền admin)
2. **Crawl truyện mới**:
   - Nhập URL truyện từ TruyenFull
   - Theo dõi tiến trình crawl real-time (progress bar, logs)
3. **Crawl hàng loạt**:
   - Nhập URL danh sách truyện + giới hạn số lượng
   - Hệ thống sẽ tự động crawl toàn bộ
4. Xem **system logs** với timestamp và color-coded entries

---

## 🤖 Hệ thống RAG — Cách hoạt động

### Pipeline xử lý

```
Câu hỏi người dùng
       │
       ▼
┌──────────────────┐
│  LangGraph Agent │  ← Điều phối toàn bộ flow
│  (State Machine) │
└────────┬─────────┘
         │
    ┌────┴────────────────────────┐
    │                             │
    ▼                             ▼
┌──────────┐              ┌──────────────┐
│ search   │              │ browse       │
│ _stories │              │ _library     │
│ (Tool)   │              │ (Tool)       │
└────┬─────┘              └──────┬───────┘
     │                           │
     ▼                           ▼
┌──────────────┐          ┌────────────┐
│Elasticsearch │          │ PostgreSQL │
│(nội dung     │          │(metadata   │
│ chương)      │          │ truyện)    │
└──────────────┘          └────────────┘
         │                       │
         └───────────┬───────────┘
                     ▼
              ┌─────────────┐
              │  Gemini LLM │  ← Tổng hợp & trả lời
              └─────────────┘
                     │
                     ▼
              Câu trả lời cho người dùng
```

### Các thành phần chính

| Thành phần              | Vai trò                                                     |
| ----------------------- | ----------------------------------------------------------- |
| **LangGraph Agent**     | State machine điều phối quá trình hỏi đáp                   |
| **search_stories tool** | Tìm kiếm nội dung chương truyện trong Elasticsearch          |
| **browse_library tool** | Truy vấn metadata (tên, tác giả, thể loại) từ PostgreSQL    |
| **Elasticsearch**       | Lưu trữ & tìm kiếm full-text nội dung chương               |
| **Redis**               | Cache session state của LangGraph agent                      |
| **Gemini AI**           | LLM để phân tích câu hỏi và tổng hợp câu trả lời           |
| **sentence-transformers** | Tạo embedding vector cho dense search (chạy local)         |

### Backfill dữ liệu vào Elasticsearch

Sau khi crawl truyện, cần backfill dữ liệu vào Elasticsearch để hệ thống tìm kiếm hoạt động:

```bash
cd backend
poetry run python -m scripts.runner
```

---

## 📁 Cấu trúc project

```
Novel_AI/
├── .env                    # Biến môi trường
├── docker-compose.yml      # Elasticsearch + Redis
├── backend/
│   ├── pyproject.toml      # Dependencies Python
│   ├── app/
│   │   ├── main.py         # FastAPI entry point
│   │   ├── api/v1/endpoints/
│   │   │   ├── auth.py     # Đăng ký, đăng nhập, JWT
│   │   │   ├── agent.py    # Chat API (RAG)
│   │   │   ├── crawler.py  # API crawl truyện
│   │   │   ├── search.py   # API tìm kiếm
│   │   │   ├── library.py  # API thư viện
│   │   │   └── chat_history.py  # Lịch sử chat
│   │   ├── services/
│   │   │   ├── langgraph_agent.py  # LangGraph state machine
│   │   │   ├── langgraph_tools.py  # Tools cho agent
│   │   │   ├── search_service.py   # Elasticsearch service
│   │   │   ├── crawler.py          # Crawler service
│   │   │   └── agent_service.py    # Agent orchestrator
│   │   ├── core/config.py  # Cấu hình hệ thống
│   │   └── db/             # Database models & connection
│   └── scripts/
│       ├── runner.py        # Backfill Elasticsearch
│       └── batch_runner.py  # Crawl hàng loạt
├── frontend/
│   ├── package.json
│   └── src/
│       ├── App.jsx
│       └── pages/
│           ├── LoginPage.jsx
│           ├── RegisterPage.jsx
│           ├── ChatPage.jsx     # Trang chat RAG
│           ├── LibraryPage.jsx  # Thư viện truyện
│           └── AdminPage.jsx    # Quản trị & crawl
```

---

## 🔌 API Endpoints

| Method | Endpoint                | Mô tả                      | Auth     |
| ------ | ----------------------- | --------------------------- | -------- |
| POST   | `/api/v1/auth/register` | Đăng ký tài khoản           | ❌        |
| POST   | `/api/v1/auth/login`    | Đăng nhập                   | ❌        |
| POST   | `/api/v1/agent/chat`    | Chat với AI Agent (RAG)     | ✅ JWT   |
| GET    | `/api/v1/chat/sessions` | Danh sách phiên chat        | ✅ JWT   |
| GET    | `/api/v1/library`       | Danh sách truyện            | ✅ JWT   |
| POST   | `/api/v1/search`        | Tìm kiếm nội dung           | ✅ JWT   |
| POST   | `/api/v1/crawl`         | Crawl truyện mới            | ✅ Admin |
| POST   | `/api/v1/batch-crawl`   | Crawl hàng loạt             | ✅ Admin |

API docs tự động: http://localhost:8000/docs

---

## 🐳 Chia sẻ Docker cho người khác

Để chia sẻ hệ thống cho người khác, chỉ cần gửi:

1. **Source code** (hoặc repo link)
2. File `.env` (với thông tin cấu hình phù hợp)

Người nhận chỉ cần chạy:

```bash
# 1. Khởi động Elasticsearch + Redis
docker-compose up -d

# 2. Cài backend
cd backend && poetry install

# 3. Cài frontend
cd frontend && npm install

# 4. Chạy backend
cd backend && poetry run uvicorn app.main:app --reload

# 5. Chạy frontend
cd frontend && npm run dev
```

> **Lưu ý:** Elasticsearch và Redis image sẽ được Docker tự động pull từ Docker Hub. Người nhận không cần cài đặt gì thêm ngoài Docker.
