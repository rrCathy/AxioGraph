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

## 待用户拍板

- 是否按 **A+B+C+D**（纯 Python、离线、可验证）改造页文本管道？这属于架构级改动，未获一句话授权前不动代码。
- E 是否列为本期目标，还是先接受"扫描页公式标未识别 + 人工/视觉按钮补录"。
- 是否允许 `pip install pymupdf4llm` 到后端解释器（Bash python 已有，scoop python 缺）。
