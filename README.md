# 幼儿视频教练（kindergarten-video-coach）

幼儿园老师的一对一视频拍摄与剪辑 AI 教练。装好即用：第一次开口自动完成项目初始化（建目录、建 10 张档案表、灌 117 条底库），之后交片子就诊断、问怎么剪就给步骤。

- **看片诊断**：先讲哪里立得住、要保留，再列缺口，分必改／建议改／加分项，并标清是素材缺了还是剪辑没组织好。
- **陪你剪**：按选镜、排序、节奏、声音、字幕版式、交付六步带练，给到剪映端点哪儿、调多少、翻车点。
- **陪你拍**：拍前给清单，规格从出片方式倒推。
- **复审与拆解**：改版只查上次建议落没落实；攒几条片子后按人出成长档案，只写可观察的行为变化。

> 边界：只服务幼儿视频的拍摄与剪辑辅导；不承接招生方案策划、安全主题活动方案、教案编写。不评价孩子性格、不给老师打分排序；园方表格文档只读不写。

## 目录结构

| 路径 | 内容 |
|---|---|
| `SKILL.md` | 技能定义、初始化流程、日常四类活儿、三档存储、交付形态、红线与资源索引 |
| `agents/doubao.yaml` / `openai.yaml` | 平台接口配置（显示名、简介、默认提示词） |
| `references/main-prompt.md` | 主提示词正本：人设、判断口径、六步带练、话术 |
| `references/init-prompt.md` | 项目初始化提示词：十表结构、建档三问、云模式口径 |
| `references/standards-library.md` | 标准条目库 47 条（S1／S2／S3 三层，L3 引用带「待校准」） |
| `references/capcut-knowledge.md` | 剪映知识包 44 条（J01—J44，未实机核验标「待核验」） |
| `references/delivery-rules.md` | 三档表与存储纪律、截帧落盘、容量预算、导出提醒 |
| `references/red-lines.md` | 措辞、隐私、园方边界红线 |
| `references/troubleshooting.md` | 故障排查与恢复指引：损坏、表头不符、档位记岔、降级、长期体检 |
| `tables/schema.json` | 10 张档案表的字段骨架（脚本读它建表） |
| `scripts/bootstrap.py` | 一键项目初始化（幂等，已存在同编号则跳过） |
| `scripts/table_io.py` | 三档读写适配：在线表／本地 Excel／Markdown，异常降级与错误码 |
| `scripts/env_probe.py` | 开工环境探测：ffmpeg／ffprobe／pillow／openpyxl／本地转写包分级 |
| `scripts/diag_media.py` | 目录扫描：元数据、镜头切点、响度清单（ffprobe 实测；可标实录／成片类型） |
| `scripts/contact_sheet.py` | 观察帧接触览图：间隔抽帧拼带时间码网格表（教练自检用；列数随横竖版自适应） |
| `scripts/frame_picker.py` | 证据帧抽取、候选／定稿核对、清单双向核对；受控清理默认 dry-run |
| `scripts/check_consistency.py` | 底库计数、表名、建档字段、条文编号引用与 schema／底库一致性校验 |
| `scripts/check_output.py` | 交付前校验：HTML 自包含、截帧落盘、禁用措辞／占位符／真名、清单核对 |
| `scripts/check_archive.py` | 档案表完整性自检：在不在、能否打开、表头是否相符、是否落在临时目录 |
| `scripts/report_render.py` | 单条诊断报告渲染器：数据 JSON／模板／帧清单分离，按名单条增量渲染，缺字段降级 |
| `assets/demo-html/` | 四份演示样例骨架：拍前清单、剪前自检、成片诊断、成长档案（虚构演示；源码仓已剥离内嵌示意帧，完整带帧版本随技能包分发） |
| `CHANGELOG.md` / `LICENSE.txt` | 版本记录；CC-BY-NC-SA-4.0 |

## 环境依赖

- Python 3（脚本基线仅标准库；`openpyxl` 可选，缺库时自动降 Markdown 表兜底）。云电脑现场可能已装 Python 与 openpyxl，能力以探测为准，不预设缺组件。
- `ffmpeg`／`ffprobe` 可选：抽帧、切点统计、响度分析、接触览图依赖；缺这些工具时对应脚本不可用，诊断退回到对话内文字描述，不阻塞建档与档案读写。
- `Pillow` 可选：接触览图、候选／定稿核对表拼图依赖；缺库时抽帧清单与核对仍可走命令行文本输出。
- 在线表建档（L1）依赖运行环境提供的在线表能力；环境不具备时自动逐级降本地 Excel／Markdown，不阻塞使用。
- 产出 HTML 内联 CSS 与图片 data URI，断网可双击打开。
- 剪映操作以教师实机版本为准；11 项菜单／入口／会员状态待真机核验（见 `references/capcut-knowledge.md` 第五节清册），核验前不写成确定说法。
- 无 Python 环境下的手工建表兜底为模型操作路径，未经脚本自测覆盖。

## 安装与加载

1. 把整个目录放入技能目录（本地用户技能目录或平台技能目录），保持 `SKILL.md` 在根目录。
2. 重开一次会话，由平台按 `name` / `displayName` 识别；也可在对话中用默认提示词触发：
   > 使用 $kindergarten-video-coach 帮我看看这条片子……
3. 首次调用自动初始化：建五个工作目录、10 张档案表、灌入底库；随后按 A／B／C 三张小卡依次建档，一次只问一个决策点。

## 命令行快速验证

```bash
# 一致性自检：底库计数、表骨架与底库源文件是否一致（不一致列出问题并非零退出）
python scripts/check_consistency.py

# 自动修复 SKILL.md 里的 AUTO 计数块
python scripts/check_consistency.py --fix

# 一键初始化（--env cloud 走在线表档位，local 走本地 Excel／Markdown）
python scripts/bootstrap.py --project <当前项目目录> --env local

# 档案表完整性自检：在不在、能否打开、表头是否相符、是否落在临时目录
python scripts/check_archive.py --project <项目目录>

# 开工环境探测：工具链与本地转写可用性分级，结果落中间件
python scripts/env_probe.py probe --out <中间件>/env_report.json

# 诊断前置扫描：元数据、切点、响度清单（自动扫描目录视频，不硬编码片名）
python scripts/diag_media.py scan --dir <片子目录>

# 证据帧：候选 probe 表 → 定稿 verify 表 → 清单双向 check；清理默认 dry-run，--confirm 才真删
python scripts/frame_picker.py probe  --video <片.mp4> --frame-dir <帧目录> --secs 0,15,45
python scripts/frame_picker.py verify --frame-dir <帧目录>
python scripts/frame_picker.py check --frame-dir <帧目录>

# 交付前校验：HTML 自包含、截帧落盘、禁用措辞/占位符/真名、帧清单核对
python scripts/check_output.py --project <项目目录> --html <交付.html> --images <截帧...> --manifest <帧目录> --names <需规避真名>

# 单条诊断报告渲染：数据 JSON／模板／帧清单分离，--stem 只渲染指定条目
python scripts/report_render.py --data <诊断.json> [--manifest <帧目录>] [--stem <片子标识>] --out <报告.html>
```

## 自测

```bash
python scripts/check_consistency.py
python scripts/check_archive.py --project <项目目录>
```

- 一致性自检：退出码 `0` 一致通过；非 `0` 列出不一致项（计数、表名、字段对不上），按提示核对 schema 与底库源文件后用 `--fix` 或手工补齐。
- 档案完整性自检：退出码 `0` 无硬问题；`1` 有 hard 问题（表缺失／损坏／表头不符／落在临时目录），按 `references/troubleshooting.md` 处置；`2` 只有 soft 提醒。

## 发布口径

- 包内不固化园所名称、地名、人名、班级实名、联系方式与特定活动节点；运行时从对话／项目空间检索，找不到留占位。
- 公开版示例均为模拟演示：老师、片子、时间码为虚构，插图为 AI 示意帧，不是真实拍摄画面。
- 涉及幼儿正脸、姓名或成片对外发布时，先提醒确认园所规定与家长授权；教练不替园方判断授权是否齐备。
- 旧版试点配置不随本包发布；双版不混发。

## 打包前清理

发布打包前先删除运行产物，避免被完整性／哈希校验误报为篡改：

```bash
# 清理 Python 缓存与 pytest 缓存（Windows PowerShell）
Get-ChildItem -Recurse -Directory -Include __pycache__,.pytest_cache | Remove-Item -Recurse -Force
Get-ChildItem -Recurse -File -Include *.pyc | Remove-Item -Force
```
