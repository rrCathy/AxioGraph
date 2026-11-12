# AxioGraph 增量架构设计（2026-11-12）

> 作者：齐活林（专家团队模式取消后由主理人直接补齐）。上游输入：`2026-11-12-incremental-prd.md`。
> 注意：本文件基于实库实码核对，修正了 PRD 附录中的两处数据张冠李戴（见 §0）。

## 0. 实库核对结论（以本节为准）

| 书 | book_id 前缀 | 节点/边 | 页 | bad页 | 候选 | 处置 |
|----|--------------|---------|-----|-------|------|------|
| 伽罗瓦理论-章璞 | `401353c5` | 120 / 146（全部 legacy） | 0 | 0 | 0 | **整书清除** |
| 简明复分析 | `a0eae8c3` | 1 confirmed + 200 legacy / 196 legacy | 182 | 0 | 3 | **保留**（legacy 节点本轮不动，用户未点名） |
| 代数拓扑 | `7559b406` | 0 / 0 | 251 | 15 | 0 | **保留**（空壳书，视觉 OCR / 自动模式的实测对象） |

- 真库 `data/axiograph.db`；`backend/axiograph.db` 是无表空壳 → 删。
- `data/lightrag/` 内容：复分析导出 + 孤儿目录 `04cac5d3` + `test-book` / `test_624894dc` 测试残留，**没有伽罗瓦目录**。随 lightrag 摘除整目录删除（全部为模型可再生数据，非用户源文件）。
- `lightrag_bridge` 引用点：`main.py`（startup/shutdown）、`routers/chat.py`（ask + ask/stream）、`routers/books.py`（ingest + delete_book）、`services/llm.py`（get_embedding_func）。
- `page_extractor.py` 依赖 `extractor._is_substantial_node`（及其依赖 `MIN_CONTENT_LEN` / `_is_valid_node` / `_get_content_len`）→ 迁入 page_extractor。
- `graph_store.save_nodes_and_edges` 仅被旧链路 `_process_book` 使用 → 随手术删除；其余函数全保留。

## 1. 模块设计

### 1.1 数据清除 + 死代码（US-3）
- `scripts/purge_galois.py`：sqlite3 backup API 先生成 `data/axiograph.db.bak-<ts>-prepurge`；按 `book_id='401353c5-…'` 精确删除 books/graph_nodes/graph_edges/chapters/pages/candidates/action_log 相关行；打印删除计数。
- 手工删除：`backend/parser.py`、`backend/extractor.py`、`backend/lightrag_bridge.py`、`backend/axiograph.db`、`data/lightrag/`。
- `routers/books.py`：删 `_process_book` / `_check_llm` / pause|resume|cancel 端点 / `_progress` 等三本字典；`get_status` 改为直读 books 表；`delete_book` 补 pages/candidates/chapters/action_log 显式清理（action_log 无 FK）。
- `main.py`：startup 仅 `init_db()`；shutdown 处理器删除。
- `services/llm.py`：删 `get_embedding_func`；新增 `chat_vision`（§1.3）。
- `routers/chat.py`：ask / ask/stream 直接走 `_build_fallback_response`（get_context_for_qa）。
- `page_extractor.py`：迁入 `_is_substantial_node` 及依赖。
- `pyproject.toml`：去掉 `lightrag-hku`、`numpy`。
- `scripts/smoke.py`：`c_graph` 允许空图谱书（跳过）与 0 边书，保留"无悬挂边 + 计数同步"断言。

### 1.2 书籍结构识别（US-2）
- 存储：新表 `book_structure(book_id PK, data_json TEXT, confirmed INT, updated_at)`。
  `data_json = {title, author, publisher, offset, offset_confidence, source, toc:[{level,title,book_page,pdf_page}]}`。JSON 整存整取，重跑覆盖，不产生残留。
- 模块 `backend/book_structure.py`：
  1. **书签路径**：`pymupdf get_toc()` → level/title/pdf_page；book_page 留空。
  2. **目录页路径**（无书签）：前 20 页内按文本层 `text_quality>=0.55` 找 `目录|目 录|Contents|CONTENTS`；命中页若是坏页则视觉模型辨认；再渲染目录页（zoom≈2）交视觉模型解析 `{level,title,book_page}` 列表（strict JSON，json_repair 兜底）。
  3. **页码偏移**：取前若干个 level≤1 条目，在正文页文本层做标题匹配（归一化后 substring），≥1 个锚点 → `offset = pdf_page - book_page`，应用到全部条目；无锚点 offset=null，交人工修正。
  4. **书名/作者**：`doc.metadata`（title/author）优先，空则封面页（第 1 页）文本/视觉提取；可编辑。
- 确认入库（`confirm_structure`）：删除本书 `entity_type='CHAPTER'` 且 metadata source=toc 的旧节点（边随 FK 级联）→ 重建 CHAPTER 节点：`review_status='confirmed'`, `created_by='human'`, `page_start=pdf_page`, `page_end=下一章节 pdf_page-1`, `chapter='p{n}-…'`, `metadata={"source":"toc","book_page":N,"level":L}`。
- 路由 `routers/structure.py`：`GET /api/books/{id}/structure`、`POST …/structure/detect`（X-Task-Id 可取消，视觉调用慢）、`POST …/structure`（保存编辑）、`POST …/structure/confirm`、`POST …/structure/toc-page {page_no}`（手动指定目录页→视觉解析，仅返回不落库）。

### 1.3 视觉 OCR（US-4）
- `config.py` 新增 `freeapi_vision_model`（默认按实测择优结果写入，可用 .env 覆盖）。
- `services/llm.py::FreeAPIProvider.chat_vision(prompt, png_bytes, …)`：OpenAI 兼容 `image_url`（data URI base64）。
- `backend/vision.py`：`ocr_page(book_id, page_no, task_id)`——render_page(zoom=2.0) → 逐字转录 prompt（阅读顺序、保留数学记号、禁止注释）→ 启发式置信度（复用 text_quality + 字符密度，0-100）→ `save_page_text(text, status='ocr'|'bad_page', confidence)`，沿用 <55 转人工；异常/空返回 → 不落库，返回 needs_manual。
- 路由：`POST /api/books/{id}/pages/{page_no}/vision-ocr`（X-Task-Id 取消语义与 extract 一致）。
- 选型实测：对 代数拓扑 的 2 个 bad_page × {nemotron-parse-2.0, glm-4.6v-flash, llama-3.2-90b-vision} 跑分，结论记 `docs/sop/vision-ocr-bakeoff.md`。
- 前端 tesseract.js 通道保留（退路），新增"视觉识别"按钮。

### 1.4 自动模式（US-5）
- `page_extractor.py`：`_auto_tasks` 状态表 + `start_auto_extract(book_id, start, end, window_size, task_id)`（守护线程串行逐窗）；`extract_window` 加 `clear_task` 开关供复用。每窗：取消检查 → 提取 → 失败重试 1 次 → 标记 failed 继续。快照 `{status, window_done, window_total, current_window, failed_windows, next_window}`。
- 路由：`POST /api/books/{id}/auto-extract`（返回 task_id）、`GET /api/books/{id}/auto-extract/{task_id}`；取消复用 `/api/tasks/{task_id}/cancel`。恢复 = 从 `next_window` 起新任务。
- 前端自动模式控制条：范围（起止页 / 章节下拉，结构确认后出现）、窗口 1/2/3（默认 2）、开始/停止/继续、进度"第 X 窗 / 共 Y 窗"（无假百分比）、失败窗口标记。候选照旧进 pending 队列人工确认。

### 1.5 整页查看器（US-1）
- `WorkbenchPanels.PageSheet` 升级：缩放三档（适应宽度 / 适应整页 / 100%），服务端渲染 zoom（clamp 0.5–3.0，已有）按档位换算后重取 PNG；`img` 宽度 = `page_width(pt) × zoom`，bbox 百分比 overlay 与引用高亮不受影响；滚动容器已有（`.ag-page-well`），`page-sheet` 在非 fit-width 档放开 `max-width`。
- 不做页间翻页（窗口导航已有）。

## 2. 前端改动清单
- `services/api.ts`：删 pause/resume/cancelExtraction；增 structure / vision-ocr / auto-extract 系列；`pageImageUrl` 加 zoom 参数。
- `types/index.ts`：BookStructure / TocItem / AutoStatus。
- `components/workbench/WorkbenchPanels.tsx`：PageSheet → PageViewer（缩放）。
- `components/Workbench.tsx`：顶栏加"视觉识别 / 书籍结构"；自动模式控制条；结构面板打开态；章节跳页复用 goPage。
- `components/workbench/BookStructurePanel.tsx`（新）。
- `theme/entityMeta.ts` + `EntityBadge`：补 CHAPTER 类型的形状/色（走 --ag-* token）。
- `i18n/translations.ts`：zh/en 补 workbench.vision*/auto*/structure* 键。

## 3. 实现顺序（依赖约束）
1. purge_galois.py + 备份 → 执行 → 删死文件 → 后端手术 → `python scripts/smoke.py`（需起栈）→ **commit A**
2. chat_vision + bake-off → 定 vision model 默认 → **记录 docs**
3. book_structure 后端 + 路由 → vision OCR 端点 → auto-extract 后端 → **commit B**
4. 前端（api/types/PageViewer/自动模式/结构面板/i18n/entityMeta）→ `npm run build` + `tsc --noEmit` → **commit C**
5. 实测：结构识别（代数拓扑）、视觉 OCR（bad_page）、自动模式 2 页窗 → smoke 全绿 → **commit D（如有修正）**

## 4. 风险与边界
- 视觉模型经 FreeLLMAPI 的图像输入格式未实测——bake-off 第一步先打通 chat_vision 通路；打不通则降级 tesseract.js + 人工（诚实报告，不硬凑）。
- 自动模式严格串行、人审确认环不自动写图谱；失败窗口可跳过，不阻塞。
- 删除操作全部先备份、按 book_id 圈定；PDF 源文件与旧 .bak 备份不动。
