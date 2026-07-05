# RAG-a-main

基于 LangChain 的 RAG 智能问答系统。

## 项目结构

```
├── backend/             # Python 后端 (FastAPI + LangChain + Milvus)
├── rag-agent-front/     # 前端 (React + TypeScript)
├── docs/                # 文档
└── README.md
```

## 快速开始

```bash
# 后端
cd backend
python -m venv venv
source venv/Scripts/activate  # Windows
pip install -r requirements.txt
cp .env.example .env          # 编辑配置
python main.py

# 前端
cd rag-agent-front
npm install
npm run dev
```

## 依赖服务

| 服务 | 用途 | 默认地址 |
|------|------|----------|
| Ollama | LLM + Embedding | `localhost:11434` |
| Milvus | 向量数据库 | `localhost:19530` |
| MySQL | 业务数据库 | `localhost:3307` |

## PDF 多模态图片文字检索（待启用）

### 功能说明

上传 PDF 时，除了提取文本，还能：
1. 将 PDF 每页渲染为图片
2. 用视觉模型（VLM）描述图片内容（图表、表格、插图等）
3. 将图片描述文本一并入库，使其可被关键词/语义检索命中

### 当前状态：⚠️ 未启用

代码逻辑已就绪，但以下依赖层均未安装/配置，整个图片检索链路处于静默降级状态：

```
PDF → pypdf 纯文本提取 ✅（正常工作）
PDF → pdf2image 页面渲染 ❌（未安装）
PDF → unstructured 结构化解析 ❌（未安装，需 C++ Build Tools）
渲染图片 → minicpm-v:8b 描述 ❌（模型未拉取，硬编码在代码中）
```

### 启用步骤

#### 1. 安装 pdf2image

```bash
pip install pdf2image==1.17.0
```

还需安装 Poppler：
- Windows: 下载 [poppler for Windows](http://blog.alivate.com.au/poppler-windows/)，解压后将 `bin/` 加入 PATH
- macOS: `brew install poppler`
- Linux: `apt install poppler-utils`

#### 2. 安装 unstructured（可选，增强表格/结构识别）

```bash
# 需先安装 Microsoft C++ Build Tools
# https://visualstudio.microsoft.com/visual-cpp-build-tools/
pip install "unstructured[pdf]>=0.16,<0.20"
```

> 装不上不影响核心功能，PDF 解析会自动降级为 pypdf。

#### 3. 拉取视觉模型

```bash
ollama pull minicpm-v:8b
```

> 约 5 GB。也可在 `.env` 中配置 `VISION_MODEL_NAME` 切换其他视觉模型（需先将代码中的硬编码改为读配置）。

#### 4. 验证

上传一份含图表的 PDF，在 Milvus 中检查是否有 `[图片X描述]` 开头的文本块入库。

### 相关文件

| 文件 | 作用 |
|------|------|
| [backend/services/document_service.py](backend/services/document_service.py) | `_extract_images_from_pdf` / `_describe_images` |
| [backend/services/rag_pipeline.py](backend/services/rag_pipeline.py) | 对话时图片描述 `_describe_chat_image` |
| [backend/requirements.txt](backend/requirements.txt) | `pdf2image` 和 `unstructured` 已注释 |
