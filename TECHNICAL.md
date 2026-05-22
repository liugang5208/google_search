# SEO 排名检测工具 V1.3 — 技术文档

## 技术栈

- **运行环境**：Python 3.8
- **GUI 框架**：tkinter + ttk
- **浏览器自动化**：selenium（Google / Google TW / Yahoo / Baidu）、undetected-chromedriver（Bing）
- **驱动管理**：webdriver-manager（自动下载 ChromeDriver）+ 内置 chromedriver.exe（兜底）
- **页面解析**：BeautifulSoup4（html.parser）
- **HTTP 请求**：requests
- **打包工具**：PyInstaller（--onefile 单文件模式）

---

## 目录与文件

```
google_search/
├── seo_rank_checker.py          # 主程序源码
├── chromedriver.exe             # 内置 ChromeDriver（兜底用，版本 109）
├── build_exe.bat                # Windows 打包脚本
├── build_mac.sh                 # macOS 打包脚本
├── seo_rank_checker_defaults.json  # 本地开发时的默认配置缓存（运行时自动生成）
├── logs/                        # 运行日志目录（运行时自动创建）
│   └── seo_YYYYMMDD_HHMMSS.log
├── README.md                    # 目录说明文档
└── TECHNICAL.md                 # 本技术文档
```

---

## 模块结构

### 常量与默认值（第 36-66 行）

| 常量 | 值 | 说明 |
|------|----|------|
| `SEED_URL` | `https://www.san-seo.com.tw/seed.php` | 关键词接口默认地址 |
| `SUBMIT_URL` | `https://www.san-seo.com.tw/get.php` | 排名提交接口默认地址 |
| `MAX_LOG_LINES` | 2000 | GUI 日志面板最大保留行数 |
| `DEFAULT_PAGES` | 1 | 每引擎默认翻页数 |
| `DEFAULT_DELAY` | 30.0 | 关键词间默认等待秒数 |
| `DEFAULT_LIMIT` | 0 | 关键词数量限制（0=全部） |

引擎标识与提交 type 代码的映射关系由 `ENGINE_META` 字典维护：

| 引擎 key | 显示名 | type 代码 |
|----------|--------|-----------|
| `google` | Google | GE |
| `google_tw` | Google TW | G |
| `yahoo` | Yahoo | Y |
| `bing` | Bing | B |
| `baidu` | 百度 | BD |

---

### 默认配置持久化（第 43-185 行）

#### `_get_config_path() -> Path`

解决 `--onefile` 打包后 `__file__` 指向临时解压目录（`_MEI*`）导致配置无法持久的问题。根据操作系统返回不同的持久化路径：

| 系统 | 配置文件路径 |
|------|-------------|
| Windows | `%LOCALAPPDATA%\SEORankChecker\seo_rank_checker_defaults.json` |
| macOS | `~/Library/Application Support/SEORankChecker/seo_rank_checker_defaults.json` |
| Linux | `$XDG_CONFIG_HOME/SEORankChecker/seo_rank_checker_defaults.json` |

#### `load_default_ui_config() -> (dict, bool)`

从持久化路径读取 JSON 配置，对各字段做范围校验（`_clamp_int` / `_clamp_float`），返回 `(配置字典, 是否成功加载)` 元组。读取失败时静默降级为内置默认值。

#### `save_default_ui_config(cfg: dict)`

将 UI 当前参数归一化（`_normalize_ui_config`）后写入持久化路径。由界面上"💾 保存为默认配置"按钮触发。

---

### 日志系统（第 86-127 行）

程序启动时在 `logs/` 目录下创建以时间戳命名的日志文件，并注册三个 Handler：

| Handler | 类型 | 级别 | 输出目标 |
|---------|------|------|---------|
| `_fh` | FileHandler | DEBUG | `logs/seo_YYYYMMDD_HHMMSS.log` |
| `_ch` | StreamHandler | INFO | 标准输出（控制台） |
| `_GuiQueueHandler` | 自定义 | 可动态调整 | GUI 日志面板队列 |

`_GuiQueueHandler` 将日志记录放入线程安全的 `queue.Queue`，由主线程的 `_poll_queue` 每 120ms 消费，避免跨线程直接操作 tkinter 控件。

---

### WebDriver 管理（第 188-304 行）

#### `_get_bundled_chromedriver() -> str`

查找打包进 exe 的 `chromedriver.exe`。`--onefile` 运行时从 `sys._MEIPASS`（PyInstaller 临时解压目录）查找；直接运行脚本时从脚本同目录查找。找不到返回空字符串。

#### `_get_driver(engine: str)`

驱动实例通过 `_driver_cache` 字典缓存，同一引擎在整个会话中复用同一个 Chrome 实例。驱动失效时自动重建。

ChromeDriver 查找优先级（非 Bing 引擎）：

```
① webdriver-manager 自动匹配当前 Chrome 版本
② 系统 PATH 中的 chromedriver（用 shutil.which 检测）
③ 内置 chromedriver.exe（打包进来的 109 版本兜底）
```

**Bing 特殊处理**：Bing 使用 `undetected_chromedriver` 以有头模式（非 headless）运行，首次启动会执行 `_bing_warmup` 访问 Bing 首页完成 session 初始化，避免触发 `rdr=1` 重定向导致搜索结果为空。

Chrome 启动参数（非 Bing）关键项说明：

| 参数 | 作用 |
|------|------|
| `--headless` | 无头模式（旧版参数，兼容 Chrome 109） |
| `--no-sandbox` | 禁用沙盒（Win7 / 容器环境必需） |
| `--disable-gpu` | 禁用 GPU（无显卡环境防崩溃） |
| `--remote-debugging-port=0` | 系统自动分配调试端口，避免端口冲突崩溃 |
| `--disable-blink-features=AutomationControlled` | 隐藏自动化特征，降低被反爬检测概率 |

---

### 关键词接口（第 307-338 行）

#### `fetch_keywords(url, limit) -> list`

向 XML 接口发 GET 请求，解析 `<sp>` 节点，提取 `<id>`、`<k>`（关键词）、`<u>`（目标域名），以 `(keyword, domain)` 为键去重后返回列表。`limit > 0` 时截取前 N 条。

XML 格式要求：

```xml
<root>
  <sp>
    <id>123</id>     <!-- 关键词唯一 ID -->
    <k>SEO优化</k>   <!-- 关键词文本 -->
    <u>example.com</u>  <!-- 目标域名 -->
  </sp>
</root>
```

---

### 结果提交接口（第 341-375 行）

#### `submit_result(kid, engine_key, rank, check_date, url) -> bool`

每条检测结果完成后自动以 GET 方式提交，参数如下：

| 参数 | 说明 |
|------|------|
| `kid` | 关键词 ID |
| `type` | 引擎代码（见 ENGINE_META） |
| `on` | 排名位次，未找到时传 0 |
| `creatdate` | 检测日期 `YYYY-MM-DD` |

返回 `True` 表示 HTTP 200，`False` 表示请求失败或非 200。

---

### 各引擎搜索实现（第 413-791 行）

所有搜索函数统一返回结构：

```python
{
    "rank": int,   # 排名位次，未找到时为 -1
    "page": int,   # 命中所在页码，未找到时为 -1
    "url":  str,   # 命中的搜索结果 URL
    "note": str,   # 附加说明（如"触发验证码"、"前N页未找到"）
}
```

#### Google / Google TW（`_google_search_base`）

用 BeautifulSoup 解析页面中带 `<h3>` 子元素的 `<a>` 链接，过滤掉 `google.` 域名的内部链接。检测到 `"unusual traffic"` 文本时判定触发验证码，返回 `rank=-1`。

#### Yahoo（`search_yahoo`）

从 `<h3>` 标签中提取链接，包含 `_yahoo_is_ad_result` 广告过滤逻辑，通过检查父节点的 class/id/aria-label 等属性以及节点文本中的广告关键词（廣告、贊助、sponsored 等）识别并跳过广告条目。第一页排名超过 10 时自动修正为 10。

#### Bing（`search_bing`）

Bing 结果链接存在两种形式：`a.tilk`（图标链接，href 为真实 URL）和 `h2 > a`（标题链接）。对于 `/ck/a?` 格式的点击追踪链接，从同条结果的 `<cite>` 标签中提取真实域名。页面检测到 `rdr=1` 重定向时自动重试一次。

#### 百度（`search_baidu`）

从 `.result` 和 `.c-container` 选择器中提取条目，优先读取 `data-real-url` 或 `mu` 属性获取真实 URL（百度搜索结果链接通常经过跳转）。

---

### 结果导出（第 794-812 行）

| 函数 | 格式 | 编码 |
|------|------|------|
| `export_csv(results, path)` | CSV | UTF-8 BOM（可直接用 Excel 打开） |
| `export_json(results, path)` | JSON 数组 | UTF-8，indent=2 |

导出字段：`keyword`、`domain`、`engine`、`rank`、`page`、`url`、`note`、`submitted`、`checked_at`。

---

### GUI 主窗口（第 839-1739 行）

#### 线程模型

GUI 运行在主线程，检测任务运行在后台 `daemon` 线程（`_worker`）。两者通过 `queue.Queue`（`_task_queue`）通信，主线程通过 `self.after(120, self._poll_queue)` 每 120ms 轮询一次队列消费消息，避免跨线程操作 tkinter 控件引发崩溃。

消息类型：

| 消息 key | 数据 | 触发时机 |
|----------|------|---------|
| `log_line` | `(level, msg)` | 日志 Handler 写入 |
| `kw_loaded` | 关键词列表 | 关键词加载完成 |
| `kw_error` | 错误字符串 | 关键词加载失败 |
| `row_checking` | 行数据字典 | 某行开始检测 |
| `row_done` | 行数据 + 进度 | 某行检测完成 |
| `done` | 完成条数 | 整个任务结束 |

#### 关键词勾选机制

结果表格第一列（`picked`）显示 `☑` / `☐` 复选标记，用字符串而非真正的 checkbox 实现，通过 `<Button-1>` 事件拦截点击。点击某行的勾选列时，会同步切换该关键词下所有引擎行的勾选状态（同一关键词 ID 的所有行联动）。列头点击触发全选/取消全选。开始检测时仅对勾选行对应的关键词发起搜索。

#### 默认配置加载时机

`__init__` → `_build_ui()` 完成后 → `_apply_default_ui_config()` 从持久化路径读取 JSON 并回填到各控件变量。

---

## 打包说明

### Windows（build_exe.bat）

使用 `py -3.8` 命令调用 Python 3.8 环境，确保与目标操作系统兼容（支持 Win7+）。

关键 PyInstaller 参数：

| 参数 | 说明 |
|------|------|
| `--onefile` | 打包为单个 exe，无需附带其他文件 |
| `--windowed` | 不显示控制台窗口（GUI 程序） |
| `--add-binary "chromedriver.exe;."` | 将内置 ChromeDriver 打入 exe |
| `--hidden-import ssl` 等 | 补充 SSL 相关模块，解决打包后 HTTPS 不可用问题 |
| `--collect-all webdriver_manager` 等 | 完整收集第三方库资源文件 |

打包产物：`dist\SEO_Rank_Checker.exe`（单文件，约 50-80 MB）。

### Win7 额外要求

- 必须使用 Python 3.8 打包（Python 3.9+ 已放弃 Win7 支持）
- 目标机器需安装 Microsoft Visual C++ 2015-2022 Redistributable
- 目标机器需安装 Chrome 109 及以下版本（与内置 chromedriver.exe 版本匹配）

---

## 已知限制

- **验证码**：Google / Yahoo / Bing 在短时间大量请求时可能触发人机验证，触发后该条结果标记为"触发验证码"，排名记为未找到。建议将关键词间隔设置为 30 秒以上。
- **Bing 有头模式**：Bing 引擎使用有头浏览器，打包后在无桌面环境（如 Server Core）下可能无法运行。
- **百度跳转链接**：百度部分结果的真实 URL 需通过 `mu` / `data-real-url` 属性获取，若属性缺失则使用原始 href，可能包含百度跳转域名。
- **页面结构变更**：各搜索引擎前端随时可能更新 HTML 结构，导致解析逻辑失效，需同步更新选择器。
