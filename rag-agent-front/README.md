# RAG Agent 前端

基于 React 18 + TypeScript + Tailwind CSS + Vite 构建的 RAG Agent 对话与知识库管理界面。

## 启动

```bash
cd rag-agent
npm install
npm run dev
```

前端运行在 `http://localhost:5173`，API 请求代理到 `http://localhost:8000`。

## 页面功能

**顶部导航** — 两个标签页切换：对话 / 知识库（快捷键 ⌘1 / ⌘2）。

**对话页** — 左侧为聊天区（Agent 流式回答、推理步骤折叠、检索来源卡片），右侧为对话列表面板（新建、切换、删除对话）。

**知识库页** — 拖拽或点击上传文档（PDF/TXT/MD/DOCX/CSV/JSON/HTML），表格展示文件名、大小、状态、上传时间，支持删除。

## 后端 API

### 对话

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/chat/stream` | 流式 SSE 对话（event: thinking / token / sources / trace / done / error） |
| `POST` | `/api/chat` | 非流式对话（降级方案） |
| `GET` | `/api/conversations` | 获取对话列表 |
| `POST` | `/api/conversations` | 新建对话 `{"title":"..."}` |
| `GET` | `/api/conversations/:id` | 获取对话详情 |
| `DELETE` | `/api/conversations/:id` | 删除对话 |

### 知识库

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/documents` | 获取文档列表 |
| `POST` | `/api/documents/upload` | 上传文档 (multipart/form-data, field: `file`) |
| `DELETE` | `/api/documents/:id` | 删除文档 |

### SSE 事件格式

```
event: thinking
data: {"type":"search","text":"查询改写：..."}

event: token
data: {"text":"增量文本"}

event: sources
data: [{"id":1,"title":"...","score":0.95,"author":"...","year":2023,"excerpt":"..."}]

event: trace
data: [{"phase":"retrieval","label":"知识库检索","detail":"...","time":"13:45"}]

event: done
data: {"conversation_id":"xxx"}

event: error
data: {"message":"错误描述"}
```

## 项目结构

```
rag-agent/
├── index.html
├── package.json / vite.config.ts / tailwind.config.js / tsconfig.json
└── src/
    ├── main.tsx / App.tsx / index.css
    ├── types.ts                  # 所有类型定义
    ├── api/client.ts             # fetch 封装（SSE 流式 + REST）
    ├── hooks/
    │   ├── useChat.ts            # 对话状态 + 会话管理
    │   └── useKnowledge.ts       # 知识库文档状态
    └── components/
        ├── Header.tsx            # 顶栏：Logo + 导航切换
        ├── ChatArea.tsx          # 聊天区：消息列表 + 内联来源/推理
        ├── ChatInput.tsx         # 输入框：Enter发送、停止按钮
        ├── ConversationPanel.tsx # 对话列表侧栏：新建/切换/删除
        ├── MessageBubble.tsx     # 消息气泡（用户蓝底 / Agent Markdown）
        ├── ThinkingSteps.tsx     # 推理步骤折叠面板
        ├── SourceChips.tsx       # 来源标签行
        ├── SourcesTab.tsx        # 检索来源卡片列表
        ├── TraceTab.tsx          # 推理过程时间线
        └── KnowledgeBase.tsx     # 知识库：上传、文档表格、删除
```
