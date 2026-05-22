# google_search — SEO 排名检测工具 V1.3

基于 Python 3.8 + Selenium 的桌面 GUI 工具，支持从远程接口拉取关键词，在 Yahoo / Google TW / Google / Bing / 百度 中自动检测目标域名的搜索排名，并将结果实时上报至远程接口。

---

## 目录内容

| 文件 / 目录 | 说明 |
|-------------|------|
| `seo_rank_checker.py` | 主程序源码，含 GUI、搜索引擎爬取、结果提交等全部逻辑 |
| `chromedriver.exe` | 内置 ChromeDriver（版本 109），用于在 webdriver-manager 和系统 PATH 均不可用时兜底 |
| `build_exe.bat` | Windows 打包脚本，使用 Python 3.8 + PyInstaller 打出单个 `SEO_Rank_Checker.exe` |
| `build_mac.sh` | macOS 打包脚本 |
| `seo_rank_checker_defaults.json` | 本地开发时生效的默认配置缓存，由程序运行时自动生成和更新 |
| `logs/` | 运行日志目录，程序首次启动后自动创建，每次运行生成一个新日志文件 |
| `README.md` | 本文件，目录说明 |
| `TECHNICAL.md` | 技术文档，包含模块结构、线程模型、打包原理等详细说明 |

---

## 快速开始

### 直接运行源码

```bash
# 安装依赖
pip install selenium webdriver-manager beautifulsoup4 requests undetected-chromedriver

# 运行
python seo_rank_checker.py
```

需要本机已安装 Google Chrome，ChromeDriver 会由 `webdriver-manager` 自动下载。

### 打包为 Windows EXE

```bat
# 双击运行，或在命令行执行
build_exe.bat
```

执行前需确保已安装 Python 3.8（脚本通过 `py -3.8` 调用）。打包完成后产物为 `dist\SEO_Rank_Checker.exe`，单文件，无需安装，可直接分发。

---

## 基本使用流程

1. 启动程序，在"检测配置"面板勾选要检测的搜索引擎
2. 确认关键词接口地址，点击"⬇ 加载关键词"拉取关键词列表
3. 在结果表格中通过"选"列勾选需要检测的关键词（支持全选/取消全选）
4. 确认提交结果接口地址，点击"💾 保存为默认配置"可将当前参数持久化
5. 点击"▶ 开始检测"，等待检测完成
6. 点击"📥 导出 CSV"或"📥 导出 JSON"保存结果到本地

---

## 默认配置持久化

点击界面上的"💾 保存为默认配置"按钮后，当前填写的接口地址、翻页数、间隔时间、数量限制会保存到系统用户目录，下次打开程序时自动加载。

配置文件实际保存位置：

- **Windows**：`%LOCALAPPDATA%\SEORankChecker\seo_rank_checker_defaults.json`
- **macOS**：`~/Library/Application Support/SEORankChecker/seo_rank_checker_defaults.json`
- **Linux**：`~/.config/SEORankChecker/seo_rank_checker_defaults.json`

> 注意：`google_search/` 目录下的 `seo_rank_checker_defaults.json` 仅在直接运行脚本（非打包 exe）时作为本地缓存存在，打包后的 exe 不会读写这个文件。

---

## 系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 7 / 10 / 11（EXE）；macOS / Linux（源码运行） |
| Python | 3.8（打包用）；3.8+ 均可直接运行源码 |
| Chrome | 需要安装 Google Chrome，版本不限；低版本（如 109）自动使用内置 chromedriver |
| Win7 额外要求 | 需安装 Microsoft Visual C++ 2015-2022 Redistributable |

---

## 更多文档

详细的模块说明、线程模型、各引擎解析逻辑、打包参数说明请参阅 [TECHNICAL.md](./TECHNICAL.md)。
