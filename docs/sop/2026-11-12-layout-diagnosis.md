# 版面 / 公式 / 示意图 诊断结论（2026-11-12）

> 针对用户三张截图的只读诊断。脚本：`scripts/diagnose_layout.py`、`scripts/diagnose_layout2.py`（可重跑）。
> 结论：用户的判断成立——问题在 PDF 识别与语义分析，不在抽取 prompt。

## 三页实测数据

| 页 | 当前 `pages.text_raw` | PyMuPDF 版面信息 | pymupdf4llm (use_ocr=False) |
|----|----------------------|------------------|------------------------------|
| 代数拓扑 p3（目录） | 1333 字符 / **109 行碎片**：`Contents / Introduction / 1 / Chapter 1. / … / 5 / 1. / What is… / 5` | 238 spans，字号 10.0/7.0/14.3，0 图像 | **1476 字符 Markdown**：`# Contents` + 表格 `\|1.\|What is algebraic topology?\|5\|`，层级/页码/π₁(S¹) 全在 |
| 代数拓扑 p14（示意图） | 1476 字符 / 58 行，分段函数被拆成 `(` / `f(2s)` / `if 0≤s≤1/2` / `g(2s−1)` | 366 spans；`get_drawings()` = 0，但 **`get_image_info()` 有 12 块**，bbox 精确给出 3 个方框：(155,401)-(275,521)、(126,577)-(186,634)、(248,577)-(302,634) | **1786 字符**：`# 2. The fundamental group` 标题层级恢复；输出 **7 个 `<!-- Start/End of picture text -->` 块**，内含 `(g·f)(s)={…}` 分段函数、`f:x→y, g:y→z, h:z→w`、`h·(g·f)≃(h·g)·f / f g h / c_x c_w` 等图内标注 |
| 简明复分析 p24（三公式） | 1035 字符，**OCR 乱码**：`炉dx + Qdy =』（招－麝）dxdy`、`(0.7)`、`詈－空` | **整页 1 张 1984×2646 位图铺满 (0,0)-(1494,1992)** + 一层劣质 OCR 文本层；`get_drawings()` = 0 | 1299 字符，6 个 picture-text 块：`(1.5)`、`炉 dx + Qdy … (1.6)`；Green/Stokes/Gauss **名字在**，公式**本体全是乱码** |

## 三个根因（必须分开处理）

1. **位置与层级**：数据一直在 PDF 里（span 的 bbox / 字号 / 字体、pymupdf4llm 的标题与表格重建），但 `page_service._blocks()` 只把 bbox 存给前端做高亮，`window_text()` 把块拼成一条纯文本再喂 LLM。**版面信息在进 LLM 前被丢光**。→ 可修，零模型。
2. **示意图**：这些图不是矢量绘图也不是普通图片，而是 **1×1 px 的线段图像**画出来的方框；`get_drawings()` 抓不到，`get_image_info()` 的 bbox 能圈出。pymupdf4llm 已经把图内文字用 `picture text` 标记与正文分开。→ 可修（按图片 bbox 聚类 + picture-text 标记），但需要区分"图内标注"与"被误归类的正文公式"。
3. **公式**：p24 **整页就是一张扫描图 + 劣质 OCR 层**，公式本体是像素，文本层里只剩乱码汉字。**从文本层永远恢复不出来**。FreeLLMAPI 视觉通路可用但当前限流严重（11 分钟跨 5 模型全 429）；本地公式 OCR（Nougat / pix2tex / MinerU）需下载 GB 级权重，本机网络受限且无 GPU。→ **不能假装修好**，应诚实标记"未识别"。

## 可行路径

| 层 | 做法 | 依赖 | 能到什么程度 | 风险 |
|----|------|------|--------------|------|
| A 版面重建 | 页文本来源换成 `pymupdf4llm.to_markdown(use_ocr=False)`；保留 span bbox 做定位 | 已装（后端 scoop python 需 pip 一次） | 标题层级、双栏阅读顺序、目录表格、上下标恢复 | `Chapter` 被表格切成 `Chap|ter`，需少量后处理 |
| B 块类型化 | 输出 `[H2]/[P]/[FORMULA]/[FIGURE]` 结构化块，`window_text` 改喂块而非纯文本 | 零新依赖 | LLM 按块类型选择性提取；示意图默认不进正文 | picture-text 里混有正文公式，需规则/LLM 二次判别 |
| C 示意图 | `get_image_info()` bbox 聚类出图区域 + picture-text 标记 → `figure_label` 排除 | 零新依赖 | 图内 `f g h c_x` 不再混进文本 | 1×1 线段图需按空间聚类，阈值要在多页上验证 |
| D 公式节点 | 有文本层页：公式块 + 编号 `(1.x)` → FORMULA 候选；扫描页：检测"整页位图 + 低文本质量"→ 标 `needs_vision` 显式提示 | 零新依赖 | 公式不再丢；编号可占位 | **转 LaTeX / 理解公式语义做不到的部分必须标"未识别"，不编造** |
| E 图像级重识别 | 视觉模型或本地公式 OCR | FreeLLMAPI（限流）/ GB 级模型 | 才可能真正拿到 p24 的三个公式 | 本机条件暂不具备，列为后续 |

## 实施结果（A+B+C+D 已落地，2026-11-12 晚）

用户一句话授权「做」后完成，验收脚本 `scripts/verify_layout.py` 可重跑。

| 页 | 改造前 | 改造后（真跑数字） |
|----|--------|--------------------|
| 代数拓扑 p3 | 1333 字符 / **109 行平铺碎片** | **3 个类型化块**：H1 `Contents` + 目录表格（含页码）+ 1 个 NOISE 页码；`layout_text` 以 `# Contents` 开头 |
| 代数拓扑 p14 | 1476 字符 / 58 行，公式与图内标注混在一起 | 9 个块：H1 + 5 正文 + 1 FORMULA + 1 FIGURE + 1 NOISE；**3 个示意图框**（bbox 精确）、图内标注 **0 条泄漏进 LLM 输入**；生成 1 个 FORMULA 候选 |
| 简明复分析 p24 | 1035 字符 OCR 乱码，公式全丢 | 13 个块；`kind=scanned_ocr` / `needs_vision=true`；编号 (1.5)(1.6)(1.8) + 名字配对 `Green 公式→(1.6)`、`Gauss 公式→(1.8)`；生成 **4 个 FORMULA 候选**，含 `Stokes 公式 (编号未识别)` 与 `待补录公式 (1.5)`，公式本体明确标注未恢复、不编造 |

端到端 `POST /extract p24-24`：**7 个 pending 候选**（LLM 抽的 Green/Stokes/Gauss 三个 THEOREM + 4 个结构化 FORMULA），全部交人工确认。LLM 429 时结构化候选不受影响（已加异常隔离）。

- 新增 `backend/page_layout.py`：`pymupdf4llm.to_markdown(use_ocr=False)` 出层级/表格，PyMuPDF span 行给位置与阅读顺序，`get_image_info()` 线段 bbox 连通分量聚类出示意图框。
- `pages` 增列 `layout_json / layout_text / page_kind / needs_vision`，按需生成并缓存；`window_text()` 改喂 `[H]/[TABLE]/[P]/[FORMULA]` 结构块，FIGURE 默认排除（选择性提取）。
- 前端右侧新增「版面」栏：块统计、页类型徽标、扫描页警示、结构化/原始文本切换、重排版面。
- 依赖：`pymupdf>=1.28` + `pymupdf4llm>=1.28,<2`（2.x 是空壳包，代码已并入 pymupdf 2.x；后端保持 1.28 线）。

**仍未做（诚实边界）**：E 图像级重识别——p24 公式本体仍需视觉模型或本地公式 OCR，当前只给占位节点并提示用户补录，不生成假 LaTeX。

## 待用户拍板

- 是否把 E 列为本期目标，还是先接受"扫描页公式标未识别 + 人工/视觉按钮补录"。
