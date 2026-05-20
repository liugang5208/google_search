#!/usr/bin/env python3.8
# -*- coding: utf-8 -*-
"""
SEO 排名检测工具 v1.2
- 关键词来源：https://www.san-seo.com.tw/seed.php (XML)
- 支持引擎：Google / Google TW / Yahoo / Bing / 百度
- 每条检测结果自动提交至 https://www.san-seo.com.tw/get.php
- 界面：tkinter 图形界面
- 日志：实时写入 logs/seo_YYYYMMDD_HHMMSS.log，GUI 底部同步展示
"""

import csv
import json
import logging
import os
import queue
import random
import subprocess
import sys
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import requests
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ══════════════════════════════════════════════════════════════
#  常量
# ══════════════════════════════════════════════════════════════

SEED_URL    = "https://www.san-seo.com.tw/seed.php"
SUBMIT_URL  = "https://www.san-seo.com.tw/get.php"
MAX_LOG_LINES = 2000

# 各引擎搜索 URL
ENGINE_SEARCH_URL = {
    "google":    "https://www.google.com/search",
    "google_tw": "https://www.google.com.tw/search",
    "yahoo":     "https://tw.search.yahoo.com/search",
    "bing":      "https://www.bing.com/search",
    "baidu":     "https://www.baidu.com/s",
}

# 引擎元信息：(显示名, type代码)
ENGINE_META = {
    "google":    ("Google",    "GE"),
    "google_tw": ("Google TW", "G"),
    "yahoo":     ("Yahoo",     "Y"),
    "bing":      ("Bing",      "B"),
    "baidu":     ("百度",       "BD"),
}

# ══════════════════════════════════════════════════════════════
#  日志系统
# ══════════════════════════════════════════════════════════════

_LOG_DIR  = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_LOG_FILE = _LOG_DIR / f"seo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logger = logging.getLogger("seo_checker")
logger.setLevel(logging.DEBUG)

_fh = logging.FileHandler(_LOG_FILE, encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter(
    fmt="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
))
logger.addHandler(_fh)

_ch = logging.StreamHandler(sys.stdout)
_ch.setLevel(logging.INFO)
_ch.setFormatter(logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S"
))
logger.addHandler(_ch)


class _GuiQueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__(logging.DEBUG)
        self._q = q

    def emit(self, record: logging.LogRecord):
        try:
            self._q.put(("log_line", (record.levelname, record.getMessage())))
        except Exception:
            pass


def _attach_gui_log_handler(q: queue.Queue):
    logger.addHandler(_GuiQueueHandler(q))


# ══════════════════════════════════════════════════════════════
#  WebDriver 管理
# ══════════════════════════════════════════════════════════════

_driver_cache: dict = {}


def _get_bundled_chromedriver() -> str:
    """
    返回打包进 exe 的 chromedriver.exe 路径。
    --onefile 运行时文件解压在 sys._MEIPASS；
    直接运行脚本时从脚本同目录查找。
    找不到返回空字符串，调用方降级到系统 PATH。
    """
    base = getattr(sys, "_MEIPASS", None) or Path(__file__).parent
    candidate = Path(base) / "chromedriver.exe"
    if candidate.exists():
        logger.info(f"使用内置 ChromeDriver: {candidate}")
        return str(candidate)
    return ""


def _get_driver(engine: str):
    if engine in _driver_cache and _driver_cache[engine] is not None:
        try:
            _ = _driver_cache[engine].current_url
            return _driver_cache[engine]
        except Exception:
            logger.warning(f"[{engine}] 旧驱动失效，重新创建")
            _driver_cache[engine] = None

    logger.info(f"[{engine}] 初始化 ChromeDriver ...")

    if engine == "bing":
        # Bing 使用 undetected_chromedriver + 有头模式，避免反爬
        import undetected_chromedriver as uc
        opts = uc.ChromeOptions()
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1440,900")
        opts.add_argument("--lang=zh-TW")
        driver = uc.Chrome(options=opts, use_subprocess=True)
        logger.info(f"[{engine}] 浏览器就绪 [undetected-chromedriver, headless=否]")
        _bing_warmup(driver)
    else:
        # 其他引擎使用普通 selenium + headless=True
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        try:
            from webdriver_manager.chrome import ChromeDriverManager
            logging.getLogger("WDM").setLevel(logging.ERROR)
            service = Service(ChromeDriverManager().install())
        except Exception as e:
            logger.warning(f"[{engine}] webdriver-manager 失败，尝试系统 PATH: {e}")
            try:
                service = Service()
                # 用一个空 URL 验证系统 PATH 中的 chromedriver 是否可用
                import shutil
                if not shutil.which("chromedriver"):
                    raise FileNotFoundError("系统 PATH 中未找到 chromedriver")
                logger.info(f"[{engine}] 使用系统 PATH 中的 chromedriver")
            except Exception as e2:
                logger.warning(f"[{engine}] 系统 PATH 不可用，尝试内置 ChromeDriver: {e2}")
                bundled = _get_bundled_chromedriver()
                if bundled:
                    service = Service(bundled)
                else:
                    logger.warning(f"[{engine}] 内置 ChromeDriver 不存在，最终降级用系统 PATH")
                    service = Service()

        opts = Options()
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        opts.add_argument("--window-size=1440,900")
        opts.add_argument("--lang=zh-TW")
        opts.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        driver = webdriver.Chrome(service=service, options=opts)
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"}
        )
        logger.info(f"[{engine}] 浏览器就绪 [selenium, headless=是]")

    _driver_cache[engine] = driver
    return driver


def _bing_warmup(driver):
    """访问 Bing 首页完成 session 初始化，避免首次搜索触发 rdr=1 重定向导致结果为空。"""
    try:
        logger.info("[bing] 预热：访问首页初始化 session ...")
        driver.get("https://www.bing.com")
        time.sleep(2)
        logger.info("[bing] 预热完成")
    except Exception as e:
        logger.warning(f"[bing] 预热失败（忽略）: {e}")


def close_all_drivers():
    for eng, drv in list(_driver_cache.items()):
        try:
            if drv:
                drv.quit()
                logger.info(f"[{eng}] 浏览器已关闭")
        except Exception as e:
            logger.warning(f"[{eng}] 关闭异常: {e}")
        _driver_cache[eng] = None


# ══════════════════════════════════════════════════════════════
#  关键词接口
# ══════════════════════════════════════════════════════════════

def fetch_keywords(url: str, limit: int = 0) -> list:
    logger.info(f"请求关键词接口: {url}")
    resp = requests.get(url, timeout=15)
    resp.encoding = "utf-8"
    raw = resp.text.strip()
    logger.debug(f"接口响应长度: {len(raw)} 字符")

    root = ET.fromstring(raw)
    items, seen = [], set()
    for sp in root.findall("sp"):
        kid    = sp.findtext("id", "").strip()
        kw     = sp.findtext("k",  "").strip()
        domain = sp.findtext("u",  "").strip()
        if not kid or not kw or not domain:
            continue
        key = (kw, domain)
        if key in seen:
            continue
        seen.add(key)
        items.append({"id": kid, "keyword": kw, "domain": domain})
        if limit and len(items) >= limit:
            break

    logger.info(
        f"关键词解析完成，共 {len(items)} 条"
        + (f"（限制前 {limit} 条）" if limit else "")
    )
    return items


# ══════════════════════════════════════════════════════════════
#  提交结果接口
# ══════════════════════════════════════════════════════════════

def submit_result(kid: str, engine_key: str, rank: int, check_date: str,
                  url: str = "") -> bool:
    """
    提交一条排名结果到 get.php
    参数：
      kid        - 关键词 ID
      engine_key - 引擎标识（"google"/"google_tw"/"yahoo"/"bing"/"baidu"）
      rank       - 排名位（未找到时传 0）
      check_date - 检测日期 "YYYY-MM-DD"
      url        - 提交接口地址（空则使用默认常量 SUBMIT_URL）
    """
    endpoint  = url.strip() or SUBMIT_URL
    type_code = ENGINE_META.get(engine_key, ("?", "?"))[1]
    params = {
        "kid":        kid,
        "type":       type_code,
        "on":         rank if rank > 0 else 0,
        "creatdate":  check_date,
    }
    try:
        resp = requests.get(endpoint, params=params, timeout=10)
        ok = resp.status_code == 200
        logger.debug(
            f"  提交结果 kid={kid} type={type_code} on={params['on']}"
            f" date={check_date}  HTTP {resp.status_code}"
            + (f"  resp: {resp.text[:60]}" if not ok else "")
        )
        return ok
    except Exception as e:
        logger.warning(f"  提交结果失败 kid={kid} engine={engine_key}: {e}")
        return False


# ══════════════════════════════════════════════════════════════
#  搜索引擎辅助
# ══════════════════════════════════════════════════════════════

def _accept_cookie(driver):
    from selenium.webdriver.common.by import By
    try:
        btn = driver.find_element(
            By.XPATH,
            '//button[contains(.,"Accept") or contains(.,"同意")'
            ' or contains(.,"接受") or contains(.,"我同意")]'
        )
        btn.click()
        time.sleep(0.8)
    except Exception:
        pass


def _extract_domain(url: str) -> str:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
        return host.lstrip("www.")
    except Exception:
        return url.lower()


def _wait_page(driver, css: str, timeout: int = 15):
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, css))
    )


# ══════════════════════════════════════════════════════════════
#  各引擎搜索实现
# ══════════════════════════════════════════════════════════════

def _google_search_base(driver, keyword: str, target_domain: str,
                         base_url: str, engine_label: str,
                         max_pages: int = 1, per_page: int = 10) -> dict:
    """Google 系通用搜索（google.com / google.com.tw）"""
    from bs4 import BeautifulSoup

    target_clean = target_domain.lower().lstrip("www.")
    rank_global  = 0
    logger.debug(f"  [{engine_label}] 搜索「{keyword}」目标: {target_domain} 最多{max_pages}页")

    for page in range(1, max_pages + 1):
        start = (page - 1) * per_page
        url   = (
            f"{base_url}"
            f"?q={urllib.parse.quote(keyword)}"
            f"&num={per_page}&start={start}&hl=zh-TW"
        )
        logger.debug(f"  [{engine_label}] 第{page}/{max_pages}页: {url}")
        try:
            driver.get(url)
            _wait_page(driver, "h3, #rso, #search")
        except Exception as e:
            logger.warning(f"  [{engine_label}] 第{page}页加载失败: {e}")
            break

        if "unusual traffic" in driver.page_source.lower():
            logger.error(f"  [{engine_label}]「{keyword}」触发验证码")
            return {"rank": -1, "page": page, "url": "", "note": "触发验证码"}

        _accept_cookie(driver)
        soup = BeautifulSoup(driver.page_source, "html.parser")

        items = []
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if not href.startswith("http") or "google." in href:
                continue
            if not a.find("h3"):
                continue
            items.append(href)

        logger.debug(f"  [{engine_label}] 第{page}页共解析 {len(items)} 条，逐条如下:")
        for _i, _href in enumerate(items, 1):
            _d = _extract_domain(_href)
            logger.debug(f"    [{_i}] {_d}  {_href[:80]}")

        page_rank = 0
        for href in items:
            page_rank  += 1
            rank_global += 1
            if target_clean in _extract_domain(href) or \
               _extract_domain(href) in target_clean:
                logger.info(
                    f"  [{engine_label}] ✓ 「{keyword}」排名 #{rank_global}"
                    f"（第{page}页）{href[:70]}"
                )
                return {"rank": rank_global, "page": page, "url": href, "note": ""}

        logger.debug(f"  [{engine_label}] 第{page}页解析{page_rank}条，未匹配")
        if page_rank == 0:
            break
        if page < max_pages:
            time.sleep(round(random.uniform(1.0, 2.0), 1))

    logger.info(f"  [{engine_label}] ✗「{keyword}」前{max_pages}页未找到 {target_domain}")
    return {"rank": -1, "page": -1, "url": "", "note": f"前{max_pages}页未找到"}


def search_google(driver, keyword, target_domain, max_pages=1):
    return _google_search_base(
        driver, keyword, target_domain,
        ENGINE_SEARCH_URL["google"], "Google", max_pages
    )


def search_google_tw(driver, keyword, target_domain, max_pages=1):
    return _google_search_base(
        driver, keyword, target_domain,
        ENGINE_SEARCH_URL["google_tw"], "Google TW", max_pages
    )


def search_yahoo(driver, keyword: str, target_domain: str, max_pages: int = 1) -> dict:
    from bs4 import BeautifulSoup

    target_clean = target_domain.lower().lstrip("www.")
    rank_global  = 0
    logger.debug(f"  [Yahoo] 搜索「{keyword}」目标: {target_domain} 最多{max_pages}页")

    for page in range(1, max_pages + 1):
        b   = (page - 1) * 10 + 1
        url = (
            f"{ENGINE_SEARCH_URL['yahoo']}"
            f"?p={urllib.parse.quote(keyword)}&b={b}&ei=utf-8"
        )
        logger.debug(f"  [Yahoo] 第{page}/{max_pages}页: {url}")
        try:
            driver.get(url)
            _wait_page(driver, "#web, .searchCenterMiddle, h3")
        except Exception as e:
            logger.warning(f"  [Yahoo] 第{page}页加载失败: {e}")
            break

        _accept_cookie(driver)
        soup      = BeautifulSoup(driver.page_source, "html.parser")
        items     = []
        for h3 in soup.find_all("h3"):
            a = h3.find("a", href=True)
            if not a:
                continue
            href = a.get("href", "")
            if not href.startswith("http"):
                continue
            items.append(href)

        logger.debug(f"  [Yahoo] 第{page}页共解析 {len(items)} 条，逐条如下:")
        for _i, _href in enumerate(items, 1):
            _d = _extract_domain(_href)
            logger.debug(f"    [{_i}] {_d}  {_href[:80]}")

        page_rank = 0

        for href in items:
            page_rank  += 1
            rank_global += 1
            if target_clean in _extract_domain(href) or \
               _extract_domain(href) in target_clean:
                logger.info(
                    f"  [Yahoo] ✓ 「{keyword}」排名 #{rank_global}"
                    f"（第{page}页）{href[:70]}"
                )
                return {"rank": rank_global, "page": page, "url": href, "note": ""}

        logger.debug(f"  [Yahoo] 第{page}页解析{page_rank}条，未匹配")
        if page_rank == 0:
            break
        if page < max_pages:
            time.sleep(round(random.uniform(1.0, 2.0), 1))

    logger.info(f"  [Yahoo] ✗「{keyword}」前{max_pages}页未找到 {target_domain}")
    return {"rank": -1, "page": -1, "url": "", "note": f"前{max_pages}页未找到"}


def search_bing(driver, keyword: str, target_domain: str, max_pages: int = 1) -> dict:
    from bs4 import BeautifulSoup
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    target_clean = target_domain.lower().lstrip("www.")
    rank_global  = 0
    logger.debug(f"  [Bing] 搜索「{keyword}」目标: {target_domain} 最多{max_pages}页")

    for page in range(1, max_pages + 1):
        first = (page - 1) * 10 + 1
        url   = (
            f"{ENGINE_SEARCH_URL['bing']}"
            f"?q={urllib.parse.quote(keyword)}&first={first}&setlang=zh-TW&cc=TW&mkt=zh-TW"
        )
        logger.debug(f"  [Bing] 第{page}/{max_pages}页: {url}")
        try:
            driver.get(url)
            try:
                WebDriverWait(driver, 20).until(
                    EC.any_of(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "#b_results")),
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".b_algo")),
                        EC.presence_of_element_located((By.TAG_NAME, "h2")),
                    )
                )
            except Exception:
                time.sleep(3)
            if "rdr=1" in driver.current_url:
                logger.warning(f"  [Bing] 第{page}页触发 rdr=1 重定向，重新请求...")
                driver.get(url)
                try:
                    WebDriverWait(driver, 20).until(
                        EC.any_of(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "#b_results")),
                            EC.presence_of_element_located((By.CSS_SELECTOR, ".b_algo")),
                            EC.presence_of_element_located((By.TAG_NAME, "h2")),
                        )
                    )
                except Exception:
                    time.sleep(3)
        except Exception as e:
            logger.warning(f"  [Bing] 第{page}页加载失败: {e}")
            break

        logger.debug(f"  [Bing] 第{page}页落地URL: {driver.current_url[:100]}")
        _accept_cookie(driver)
        soup      = BeautifulSoup(driver.page_source, "html.parser")
        page_rank = 0

        items = soup.select(".b_algo")
        if not items:
            logger.debug(f"  [Bing] 未找到 .b_algo，尝试备用选择器 #b_results li")
            items = soup.select("#b_results li")

        logger.debug(f"  [Bing] 第{page}页共解析 {len(items)} 条，逐条如下:")
        for _i, _li in enumerate(items, 1):
            _tilk  = _li.find("a", class_="tilk", href=True)
            _h2    = _li.find("h2")
            _a     = _tilk or (_h2.find("a", href=True) if _h2 else _li.find("a", href=True))
            _href  = _a.get("href", "") if _a else ""
            if _href.startswith("http") and "/ck/a?" in _href:
                _cite = _li.find("cite")
                _ct   = _cite.get_text(strip=True) if _cite else ""
                if _ct:
                    _raw  = _ct.split("›")[0].strip().rstrip("/")
                    _href = _raw if _raw.startswith("http") else "https://" + _raw
                else:
                    _href = "(ck/a无cite)"
            _d = _extract_domain(_href) if _href.startswith("http") else "(非http)"
            logger.debug(f"    [{_i}] {_d}  {_href[:80]}")

        for li in items:
            # 优先用 a.tilk（Bing 图标链接，href 即真实 URL）
            # 其次用 h2>a（标题链接），最后兜底取所有 http 链接
            tilk_a   = li.find("a", class_="tilk", href=True)
            h2       = li.find("h2")
            h2_a     = h2.find("a", href=True) if h2 else None

            if tilk_a:
                href = tilk_a.get("href", "")
            elif h2_a:
                href = h2_a.get("href", "")
            else:
                all_links = [
                    a.get("href", "")
                    for a in li.find_all("a", href=True)
                    if a.get("href", "").startswith("http")
                ]
                href = all_links[0] if all_links else ""

            # bing.com/ck/a?... 是点击追踪链接，无法静态解析真实 URL
            # 改从同一条结果的 <cite> 标签取显示用的真实域名
            if "/ck/a?" in href:
                cite = li.find("cite")
                cite_text = cite.get_text(strip=True) if cite else ""
                if cite_text:
                    raw = cite_text.split("›")[0].strip().rstrip("/")
                    if raw.startswith("http"):
                        href = raw
                    else:
                        href = "https://" + raw
                else:
                    continue

            if not href.startswith("http"):
                continue

            page_rank  += 1
            rank_global += 1
            d = _extract_domain(href)
            logger.debug(f"  [Bing] #{rank_global} {d}  {href[:70]}")
            if target_clean in d or d in target_clean:
                logger.info(
                    f"  [Bing] ✓ 「{keyword}」排名 #{rank_global}"
                    f"（第{page}页）{href[:70]}"
                )
                return {"rank": rank_global, "page": page, "url": href, "note": ""}

        logger.debug(f"  [Bing] 第{page}页解析{page_rank}条，未匹配")
        if page_rank == 0:
            logger.warning(f"  [Bing] 第{page}页解析结果为空，可能被拦截")
            break
        if page < max_pages:
            time.sleep(round(random.uniform(1.0, 2.0), 1))

    logger.info(f"  [Bing] ✗「{keyword}」前{max_pages}页未找到 {target_domain}")
    return {"rank": -1, "page": -1, "url": "", "note": f"前{max_pages}页未找到"}


def search_baidu(driver, keyword: str, target_domain: str, max_pages: int = 1) -> dict:
    from bs4 import BeautifulSoup

    target_clean = target_domain.lower().lstrip("www.")
    rank_global  = 0
    logger.debug(f"  [Baidu] 搜索「{keyword}」目标: {target_domain} 最多{max_pages}页")

    for page in range(1, max_pages + 1):
        pn  = (page - 1) * 10
        url = (
            f"{ENGINE_SEARCH_URL['baidu']}"
            f"?wd={urllib.parse.quote(keyword)}&pn={pn}&rn=10"
        )
        logger.debug(f"  [Baidu] 第{page}/{max_pages}页: {url}")
        try:
            driver.get(url)
            _wait_page(driver, "#content_left, #results, h3")
        except Exception as e:
            logger.warning(f"  [Baidu] 第{page}页加载失败: {e}")
            break

        _accept_cookie(driver)
        soup      = BeautifulSoup(driver.page_source, "html.parser")
        items     = []
        for item in soup.select(".result, .c-container"):
            a = item.find("a", href=True)
            if not a or not item.find("h3"):
                continue
            href = a.get("href", "")
            real = item.get("mu") or item.get("data-real-url") or href
            items.append(real)

        logger.debug(f"  [Baidu] 第{page}页共解析 {len(items)} 条，逐条如下:")
        for _i, _href in enumerate(items, 1):
            _d = _extract_domain(_href) if _href.startswith("http") else "(非http)"
            logger.debug(f"    [{_i}] {_d}  {_href[:80]}")

        page_rank = 0

        for real in items:
            page_rank  += 1
            rank_global += 1
            if target_clean in real.lower():
                logger.info(
                    f"  [Baidu] ✓ 「{keyword}」排名 #{rank_global}"
                    f"（第{page}页）{real[:70]}"
                )
                return {"rank": rank_global, "page": page, "url": real, "note": ""}

        logger.debug(f"  [Baidu] 第{page}页解析{page_rank}条，未匹配")
        if page_rank == 0:
            break
        if page < max_pages:
            time.sleep(round(random.uniform(1.0, 2.0), 1))

    logger.info(f"  [Baidu] ✗「{keyword}」前{max_pages}页未找到 {target_domain}")
    return {"rank": -1, "page": -1, "url": "", "note": f"前{max_pages}页未找到"}


# 引擎 key -> 搜索函数映射
_ENGINE_FN = {
    "google":    search_google,
    "google_tw": search_google_tw,
    "yahoo":     search_yahoo,
    "bing":      search_bing,
    "baidu":     search_baidu,
}


# ══════════════════════════════════════════════════════════════
#  结果导出
# ══════════════════════════════════════════════════════════════

def export_csv(results: list, path: str):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=[
            "keyword", "domain", "engine", "rank", "page",
            "url", "note", "submitted", "checked_at"
        ])
        w.writeheader()
        w.writerows(results)
    logger.info(f"CSV 已导出 → {path}（{len(results)} 条）")


def export_json(results: list, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info(f"JSON 已导出 → {path}（{len(results)} 条）")


# ══════════════════════════════════════════════════════════════
#  自定义按钮组件（悬停变色）
# ══════════════════════════════════════════════════════════════

class _HoverButton(tk.Button):
    """支持鼠标悬停高亮的按钮"""

    def __init__(self, master, bg_normal, bg_hover, **kw):
        super().__init__(master, bg=bg_normal, activebackground=bg_hover,
                         activeforeground=kw.get("fg", "white"),
                         relief="flat", cursor="hand2", **kw)
        self._bg_normal = bg_normal
        self._bg_hover  = bg_hover
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, _e):
        if str(self["state"]) != "disabled":
            self.config(bg=self._bg_hover)

    def _on_leave(self, _e):
        self.config(bg=self._bg_normal)


# ══════════════════════════════════════════════════════════════
#  GUI 主窗口
# ══════════════════════════════════════════════════════════════

class SEOCheckerApp(tk.Tk):

    COL_DEFS = [
        ("id",         "#",         46,  "center"),
        ("keyword",    "关键词",   130,  "w"),
        ("domain",     "目标域名", 155,  "w"),
        ("engine",     "引擎",      72,  "center"),
        ("rank",       "排名",      55,  "center"),
        ("page",       "页码",      48,  "center"),
        ("url",        "命中 URL", 240,  "w"),
        ("note",       "备注",      90,  "w"),
        ("submitted",  "已提交",    60,  "center"),
        ("checked_at", "检测时间", 135,  "center"),
    ]

    STATUS_COLORS = {
        "running": "#2563eb",
        "done":    "#16a34a",
        "error":   "#dc2626",
        "idle":    "#64748b",
    }

    LEVEL_TAG = {
        "DEBUG":    "tag_debug",
        "INFO":     "tag_info",
        "WARNING":  "tag_warn",
        "ERROR":    "tag_error",
        "CRITICAL": "tag_critical",
    }

    def __init__(self):
        super().__init__()
        self.title("SEO 排名检测工具 v1.2")
        self.geometry("1160x880")
        self.minsize(960, 680)
        self.configure(bg="#f0f4f8")

        self._keywords: list = []
        self._results:  list = []
        self._task_queue: queue.Queue = queue.Queue()
        self._running = False
        self._stop_event = threading.Event()

        _attach_gui_log_handler(self._task_queue)
        self._build_ui()
        self._poll_queue()

        logger.info("=" * 60)
        logger.info("SEO 排名检测工具 v1.2  启动")
        logger.info(f"日志文件: {_LOG_FILE}")
        logger.info("=" * 60)

    # ── UI ──────────────────────────────────────────────────

    def _build_ui(self):
        self._build_topbar()
        self._build_config_panel()
        self._build_toolbar()
        self._build_main_paned()
        self._build_statusbar()

    # ── 顶栏 ─────────────────────────────────────────────────

    def _build_topbar(self):
        bar = tk.Frame(self, bg="#1e3a8a", height=54)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        tk.Label(bar, text="🔍  SEO 排名检测工具",
                 bg="#1e3a8a", fg="white",
                 font=("Helvetica", 17, "bold")).pack(side="left", padx=22)
        tk.Label(bar, text=f"日志: {_LOG_FILE.name}",
                 bg="#1e3a8a", fg="#93c5fd",
                 font=("Helvetica", 9)).pack(side="right", padx=18)
        tk.Label(bar, text="v1.2",
                 bg="#1e3a8a", fg="#6b9cd8",
                 font=("Helvetica", 9)).pack(side="right", padx=4)

    # ── 配置面板 ──────────────────────────────────────────────

    def _build_config_panel(self):
        outer = tk.Frame(self, bg="#f0f4f8")
        outer.pack(fill="x", padx=14, pady=(10, 2))

        frame = tk.LabelFrame(
            outer, text="  检测配置  ",
            bg="#f0f4f8", fg="#334155",
            font=("Helvetica", 10, "bold"),
            padx=12, pady=8
        )
        frame.pack(fill="x")

        # ── 行0：引擎勾选 ──────────────────────────────────
        r0 = tk.Frame(frame, bg="#f0f4f8")
        r0.pack(fill="x", pady=(2, 4))

        tk.Label(r0, text="搜索引擎:", bg="#f0f4f8", fg="#475569",
                 font=("Helvetica", 10, "bold"),
                 width=10, anchor="e").pack(side="left", padx=(0, 8))

        self._engine_vars = {}
        engine_cfg = [
            ("yahoo",     "Yahoo",     True,  "#6d28d9"),
            ("google_tw", "Google TW", False, "#1a56db"),
            ("google",    "Google",    False, "#1a56db"),
            ("bing",      "Bing",      False, "#0369a1"),
            ("baidu",     "百度",      False, "#dc2626"),
        ]
        for key, label, default, color in engine_cfg:
            var = tk.BooleanVar(value=default)
            self._engine_vars[key] = var
            cb = tk.Checkbutton(
                r0, text=label, variable=var,
                bg="#f0f4f8", fg=color,
                selectcolor="#dbeafe",
                activebackground="#f0f4f8",
                font=("Helvetica", 10, "bold"),
                cursor="hand2"
            )
            cb.pack(side="left", padx=(0, 14))

        # ── 行1：参数设置 ──────────────────────────────────
        r1 = tk.Frame(frame, bg="#f0f4f8")
        r1.pack(fill="x", pady=(0, 4))

        def _spin_group(parent, label, var, frm, to, inc, w, fmt=None, lbl_width=None):
            lbl_kw = {}
            if lbl_width is not None:
                lbl_kw["width"] = lbl_width
                lbl_kw["anchor"] = "e"
            tk.Label(parent, text=label, bg="#f0f4f8", fg="#475569",
                     font=("Helvetica", 10), **lbl_kw).pack(side="left", padx=(0, 4))
            kw = dict(from_=frm, to=to, increment=inc, width=w, textvariable=var)
            if fmt:
                kw["format"] = fmt
            ttk.Spinbox(parent, **kw).pack(side="left", padx=(0, 18))

        self._var_pages = tk.IntVar(value=1)
        self._var_delay = tk.DoubleVar(value=30.0)
        self._var_limit = tk.IntVar(value=0)

        _spin_group(r1, "每引擎翻页数:", self._var_pages, 1, 20, 1, 5, lbl_width=10)
        _spin_group(r1, "关键词间隔(秒):", self._var_delay, 1, 120, 1.0, 6, "%.1f")
        _spin_group(r1, "数量限制:", self._var_limit, 0, 9999, 1, 6)
        tk.Label(r1, text="(0=全部)", bg="#f0f4f8", fg="#94a3b8",
                 font=("Helvetica", 9)).pack(side="left", padx=(0, 20))

        tk.Label(r1, text="日志级别:", bg="#f0f4f8", fg="#475569",
                 font=("Helvetica", 10)).pack(side="left", padx=(0, 4))
        self._var_log_level = tk.StringVar(value="INFO")
        level_cb = ttk.Combobox(
            r1, textvariable=self._var_log_level,
            values=["DEBUG", "INFO", "WARNING", "ERROR"],
            state="readonly", width=9
        )
        level_cb.pack(side="left")
        level_cb.bind("<<ComboboxSelected>>", self._on_log_level_change)

        # ── 行2：关键词接口 ────────────────────────────────
        r2 = tk.Frame(frame, bg="#f0f4f8")
        r2.pack(fill="x", pady=(0, 4))

        tk.Label(r2, text="关键词接口:", bg="#f0f4f8", fg="#475569",
                 font=("Helvetica", 10),
                 width=10, anchor="e").pack(side="left", padx=(0, 4))
        self._var_seed_url = tk.StringVar(value=SEED_URL)
        tk.Entry(r2, textvariable=self._var_seed_url, width=50,
                 fg="#334155", relief="solid", bd=1,
                 font=("Helvetica", 10)).pack(side="left", padx=(0, 10))

        _HoverButton(
            r2, bg_normal="#dc2626", bg_hover="#b91c1c",
            text="  ⬇  加载关键词  ", fg="white",
            font=("Helvetica", 10, "bold"),
            padx=8, pady=4,
            command=self._load_keywords
        ).pack(side="left")

        self._lbl_kw_count = tk.Label(r2, text="", bg="#f0f4f8",
                                       fg="#64748b", font=("Helvetica", 9))
        self._lbl_kw_count.pack(side="left", padx=10)

        # ── 行3：提交结果接口 ──────────────────────────────
        r3 = tk.Frame(frame, bg="#f0f4f8")
        r3.pack(fill="x", pady=(0, 2))

        tk.Label(r3, text="提交结果接口:", bg="#f0f4f8", fg="#475569",
                 font=("Helvetica", 10),
                 width=10, anchor="e").pack(side="left", padx=(0, 4))
        self._var_submit_url = tk.StringVar(value=SUBMIT_URL)
        tk.Entry(r3, textvariable=self._var_submit_url, width=50,
                 fg="#334155", relief="solid", bd=1,
                 font=("Helvetica", 10)).pack(side="left", padx=(0, 10))
        tk.Label(r3, text="(每条检测完成后自动 GET 提交)",
                 bg="#f0f4f8", fg="#94a3b8",
                 font=("Helvetica", 9)).pack(side="left")

    # ── 工具栏 ────────────────────────────────────────────────

    def _build_toolbar(self):
        bar = tk.Frame(self, bg="#e8edf3", height=46)
        bar.pack(fill="x", padx=0)
        bar.pack_propagate(False)

        inner = tk.Frame(bar, bg="#e8edf3")
        inner.pack(side="left", padx=14, pady=6)

        # 主操作按钮
        self._btn_start = _HoverButton(
            inner, bg_normal="#dc2626", bg_hover="#b91c1c",
            text="  ▶  开始检测  ", fg="white",
            font=("Helvetica", 11, "bold"), padx=10, pady=4,
            command=self._start
        )
        self._btn_start.pack(side="left", padx=(0, 6))

        self._btn_stop = _HoverButton(
            inner, bg_normal="#9f1239", bg_hover="#881337",
            text="  ⏹  停止  ", fg="white",
            font=("Helvetica", 11, "bold"), padx=10, pady=4,
            command=self._stop, state="disabled"
        )
        self._btn_stop.pack(side="left", padx=(0, 18))

        # 分隔线
        tk.Frame(inner, bg="#cbd5e1", width=1).pack(side="left", fill="y", padx=(0, 16))

        # 辅助按钮组
        for text, cmd, bg, hover in [
            ("📥 导出 CSV",   self._export_csv,    "#0f766e", "#0d6b64"),
            ("📥 导出 JSON",  self._export_json,   "#0f766e", "#0d6b64"),
            ("📂 日志目录",   self._open_log_dir,  "#7c3aed", "#6d28d9"),
            ("🗑  清空结果",   self._clear_results, "#64748b", "#475569"),
        ]:
            _HoverButton(
                inner, bg_normal=bg, bg_hover=hover,
                text=text, fg="white",
                font=("Helvetica", 10), padx=8, pady=4,
                command=cmd
            ).pack(side="left", padx=(0, 6))

        # 进度条区域
        right = tk.Frame(bar, bg="#e8edf3")
        right.pack(side="right", padx=16, pady=6)

        self._lbl_progress = tk.Label(right, text="0 / 0",
                                       bg="#e8edf3", fg="#475569",
                                       font=("Helvetica", 9))
        self._lbl_progress.pack(side="right", padx=(6, 0))

        self._progress_var = tk.DoubleVar(value=0)
        style = ttk.Style()
        style.configure("Green.Horizontal.TProgressbar",
                         troughcolor="#d1fae5",
                         background="#16a34a",
                         thickness=14)
        self._progressbar = ttk.Progressbar(
            right, variable=self._progress_var,
            maximum=100, length=240, mode="determinate",
            style="Green.Horizontal.TProgressbar"
        )
        self._progressbar.pack(side="right")

    # ── 主体：结果表格 + 日志面板 ─────────────────────────────

    def _build_main_paned(self):
        paned = tk.PanedWindow(self, orient="vertical",
                               bg="#cbd5e1", sashwidth=5, sashrelief="flat")
        paned.pack(fill="both", expand=True, padx=14, pady=(6, 4))

        # 上：结果表格
        top = tk.Frame(paned, bg="#f0f4f8")
        paned.add(top, stretch="always", minsize=160)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview",
                         font=("Helvetica", 10), rowheight=26,
                         background="#ffffff", fieldbackground="#ffffff",
                         foreground="#1e293b")
        style.configure("Treeview.Heading",
                         font=("Helvetica", 10, "bold"),
                         background="#dde3ed", foreground="#1e293b",
                         relief="flat")
        style.map("Treeview", background=[("selected", "#bfdbfe")])

        cols = [c[0] for c in self.COL_DEFS]
        self._tree = ttk.Treeview(top, columns=cols, show="headings",
                                   selectmode="browse")
        for cid, label, width, anchor in self.COL_DEFS:
            self._tree.heading(cid, text=label, anchor="center")
            self._tree.column(cid, width=width, anchor=anchor,
                               stretch=(cid == "url"))

        self._tree.tag_configure("found",    background="#f0fdf4", foreground="#15803d")
        self._tree.tag_configure("notfound", background="#fff7ed", foreground="#c2410c")
        self._tree.tag_configure("checking", background="#eff6ff", foreground="#1d4ed8")
        self._tree.tag_configure("error",    background="#fef2f2", foreground="#b91c1c")

        vsb = ttk.Scrollbar(top, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(top, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side="right",  fill="y")
        hsb.pack(side="bottom", fill="x")
        self._tree.pack(fill="both", expand=True)
        self._tree.bind("<Double-1>", self._on_double_click)

        # 下：日志面板
        log_frame = tk.Frame(paned, bg="#0f172a")
        paned.add(log_frame, stretch="always", minsize=100)

        log_header = tk.Frame(log_frame, bg="#1e293b", height=28)
        log_header.pack(fill="x")
        log_header.pack_propagate(False)
        tk.Label(log_header, text="📋  运行日志",
                 bg="#1e293b", fg="#94a3b8",
                 font=("Courier", 9, "bold")).pack(side="left", padx=10)

        for txt, cmd in [("打开日志文件", self._open_log_file),
                          ("清空日志",    self._clear_log)]:
            tk.Button(log_header, text=txt, command=cmd,
                      bg="#334155", fg="#94a3b8", font=("Courier", 8),
                      relief="flat", padx=7, pady=1,
                      activebackground="#475569", activeforeground="white",
                      cursor="hand2").pack(side="right", padx=4, pady=3)

        self._log_text = tk.Text(
            log_frame, bg="#0f172a", fg="#e2e8f0",
            font=("Courier", 9), wrap="none",
            state="disabled", relief="flat",
            insertbackground="white", selectbackground="#334155"
        )
        log_vsb = ttk.Scrollbar(log_frame, orient="vertical",
                                  command=self._log_text.yview)
        log_hsb = ttk.Scrollbar(log_frame, orient="horizontal",
                                  command=self._log_text.xview)
        self._log_text.configure(yscrollcommand=log_vsb.set,
                                  xscrollcommand=log_hsb.set)
        log_vsb.pack(side="right",  fill="y")
        log_hsb.pack(side="bottom", fill="x")
        self._log_text.pack(fill="both", expand=True)

        self._log_text.tag_configure("tag_time",     foreground="#475569")
        self._log_text.tag_configure("tag_debug",    foreground="#64748b")
        self._log_text.tag_configure("tag_info",     foreground="#94a3b8")
        self._log_text.tag_configure("tag_warn",     foreground="#fbbf24")
        self._log_text.tag_configure("tag_error",    foreground="#f87171")
        self._log_text.tag_configure("tag_critical", foreground="#c084fc")

    # ── 状态栏 ────────────────────────────────────────────────

    def _build_statusbar(self):
        bar = tk.Frame(self, bg="#dde3ed", height=28)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self._lbl_status = tk.Label(bar, text="就绪",
                                     bg="#dde3ed", fg="#475569",
                                     font=("Helvetica", 10), anchor="w")
        self._lbl_status.pack(side="left", padx=12)
        self._lbl_time = tk.Label(bar, text="",
                                   bg="#dde3ed", fg="#94a3b8",
                                   font=("Helvetica", 9), anchor="e")
        self._lbl_time.pack(side="right", padx=12)

    # ── 日志面板 ──────────────────────────────────────────────

    def _append_log_line(self, level: str, msg: str):
        tag = self.LEVEL_TAG.get(level, "tag_info")
        ts  = datetime.now().strftime("%H:%M:%S")
        self._log_text.configure(state="normal")
        self._log_text.insert("end", f"[{ts}] ", "tag_time")
        self._log_text.insert("end", f"[{level:<8}]  ", tag)
        self._log_text.insert("end", msg + "\n", tag)
        total = int(self._log_text.index("end-1c").split(".")[0])
        if total > MAX_LOG_LINES:
            self._log_text.delete("1.0", f"{total - MAX_LOG_LINES}.0")
        self._log_text.configure(state="disabled")
        self._log_text.see("end")

    def _clear_log(self):
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def _open_log_file(self):
        if _LOG_FILE.exists():
            _open_path(str(_LOG_FILE))
        else:
            messagebox.showinfo("提示", "日志文件尚未创建")

    def _open_log_dir(self):
        _open_path(str(_LOG_DIR))

    # ── 状态 ─────────────────────────────────────────────────

    def _set_status(self, msg: str, color: str = "idle"):
        self._lbl_status.config(
            text=msg,
            fg=self.STATUS_COLORS.get(color, "#475569")
        )
        self._lbl_time.config(text=datetime.now().strftime("%H:%M:%S"))

    def _on_log_level_change(self, _e=None):
        level_int = getattr(logging, self._var_log_level.get(), logging.INFO)
        for h in logger.handlers:
            if isinstance(h, _GuiQueueHandler):
                h.setLevel(level_int)
        logger.info(f"GUI 日志级别切换为 {self._var_log_level.get()}")

    # ── 加载关键词 ────────────────────────────────────────────

    def _load_keywords(self):
        self._set_status("正在加载关键词...", "running")
        self.update_idletasks()
        url   = self._var_seed_url.get().strip()
        limit = self._var_limit.get()
        logger.info(f"加载关键词  接口: {url}  限制: {limit if limit else '全部'}")

        def _do():
            try:
                items = fetch_keywords(url, limit)
                self._task_queue.put(("kw_loaded", items))
            except Exception as e:
                logger.error(f"关键词加载失败: {e}")
                self._task_queue.put(("kw_error", str(e)))

        threading.Thread(target=_do, daemon=True).start()

    # ── 开始 / 停止 ───────────────────────────────────────────

    def _start(self):
        if not self._keywords:
            messagebox.showwarning("提示", "请先点击【加载关键词】")
            return
        engines = [k for k, v in self._engine_vars.items() if v.get()]
        if not engines:
            messagebox.showwarning("提示", "请至少勾选一个搜索引擎")
            return

        self._running = True
        self._stop_event.clear()
        self._btn_start.config(state="disabled", bg="#9ca3af")
        self._btn_stop.config(state="normal",    bg="#9f1239")
        self._results.clear()
        self._set_status("检测中...", "running")

        submit_url = self._var_submit_url.get().strip()
        params = {
            "keywords":   self._keywords,
            "engines":    engines,
            "pages":      self._var_pages.get(),
            "delay":      self._var_delay.get(),
            "submit_url": submit_url,
        }
        logger.info("═" * 56)
        logger.info(f"新建检测任务  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(
            f"引擎: {', '.join(ENGINE_META[e][0] for e in engines)}  "
            f"翻页数: {params['pages']}  间隔: {params['delay']}s  "
            f"关键词数: {len(self._keywords)}"
        )
        logger.info(f"提交接口: {submit_url or SUBMIT_URL}")
        logger.info("═" * 56)
        threading.Thread(target=self._worker, args=(params,), daemon=True).start()

    def _stop(self):
        self._stop_event.set()
        logger.warning(">>> 用户手动停止 <<<")
        self._set_status("正在停止...", "error")

    # ── 后台工作线程 ──────────────────────────────────────────

    def _worker(self, params: dict):
        keywords    = params["keywords"]
        engines     = params["engines"]
        pages       = params["pages"]
        delay       = params["delay"]
        submit_url  = params["submit_url"]
        total       = len(keywords) * len(engines)
        done       = 0
        found      = 0
        submitted  = 0
        t_start    = time.time()

        for idx, item in enumerate(keywords, 1):
            if self._stop_event.is_set():
                break

            kw     = item["keyword"]
            domain = item["domain"]
            kid    = item["id"]
            today  = datetime.now().strftime("%Y-%m-%d")

            logger.info(f"──── [{idx}/{len(keywords)}] 「{kw}」目标: {domain} ────")

            for eng in engines:
                if self._stop_event.is_set():
                    break

                eng_label = ENGINE_META[eng][0]
                row_id    = f"{kid}_{eng}"

                self._task_queue.put(("row_checking", {
                    "row_id": row_id, "keyword": kw,
                    "domain": domain, "engine": eng_label, "id": kid,
                }))
                logger.info(f"  [{eng_label}] 检索: 「{kw}」  目标: {domain}")

                # 搜索
                try:
                    drv = _get_driver(eng)
                    res = _ENGINE_FN[eng](drv, kw, domain, max_pages=pages)
                except Exception as e:
                    logger.error(f"  [{eng_label}] 检索异常: {e}")
                    res = {"rank": -1, "page": -1, "url": "", "note": str(e)[:80]}

                rank_val = res["rank"]
                if rank_val > 0:
                    found += 1
                    logger.info(
                        f"  [{eng_label}] ✓ 排名 #{rank_val}"
                        f"（第{res['page']}页）{res.get('url','')[:60]}"
                    )
                else:
                    logger.warning(
                        f"  [{eng_label}] ✗ 前{pages}页未找到  ({res.get('note','')})"
                    )

                # 提交结果
                ok = submit_result(kid, eng, rank_val, today, url=submit_url)
                if ok:
                    submitted += 1
                    logger.info(f"  [{eng_label}] 提交排名成功")
                else:
                    logger.warning(f"  [{eng_label}] 提交排名失败")

                # 记录
                record = {
                    "id":         kid,
                    "keyword":    kw,
                    "domain":     domain,
                    "engine":     eng_label,
                    "rank":       rank_val if rank_val > 0 else "未找到",
                    "page":       res["page"] if res["page"] > 0 else "-",
                    "url":        res.get("url", ""),
                    "note":       res.get("note", ""),
                    "submitted":  "✓" if ok else "✗",
                    "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                self._results.append(record)
                done += 1
                pct     = done / total * 100
                elapsed = time.time() - t_start
                eta     = (elapsed / done * (total - done)) if done else 0
                logger.info(
                    f"  进度: {done}/{total} ({pct:.1f}%)  "
                    f"已用时: {elapsed:.0f}s  预计剩余: {eta:.0f}s"
                )

                self._task_queue.put(("row_done", {
                    "row_id": row_id, "record": record,
                    "done": done, "total": total, "pct": pct,
                }))

            # 关键词间等待
            if not self._stop_event.is_set() and idx < len(keywords):
                actual = max(delay + random.uniform(-0.5, 0.5), 1.0)
                logger.debug(f"  等待 {actual:.1f}s ...")
                time.sleep(actual)

        elapsed_total = time.time() - t_start
        logger.info("═" * 56)
        if self._stop_event.is_set():
            logger.warning(
                f"任务中断  已完成 {done}/{total}  "
                f"找到排名 {found}  提交成功 {submitted}"
            )
        else:
            logger.info(
                f"✅ 任务完成！检测 {done} 条  找到排名 {found}  "
                f"提交成功 {submitted}  耗时 {elapsed_total:.1f}s"
            )
        logger.info("═" * 56)
        self._task_queue.put(("done", done))

    # ── 队列轮询 ─────────────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                msg, data = self._task_queue.get_nowait()

                if msg == "log_line":
                    self._append_log_line(data[0], data[1])

                elif msg == "kw_loaded":
                    self._keywords = data
                    self._lbl_kw_count.config(text=f"✓ 已加载 {len(data)} 条")
                    self._set_status(f"关键词加载完成，共 {len(data)} 条", "done")
                    self._prefill_table()

                elif msg == "kw_error":
                    self._set_status(f"加载失败：{data}", "error")
                    messagebox.showerror("接口错误", data)

                elif msg == "row_checking":
                    d = data
                    row_id = d["row_id"]
                    if self._tree.exists(row_id):
                        self._tree.item(
                            row_id, tags=("checking",),
                            values=(
                                d["id"], d["keyword"], d["domain"],
                                d["engine"], "…", "…", "", "检测中", "…",
                                datetime.now().strftime("%H:%M:%S")
                            )
                        )
                        self._tree.see(row_id)

                elif msg == "row_done":
                    d      = data
                    r      = d["record"]
                    row_id = d["row_id"]
                    tag = ("found"
                           if isinstance(r["rank"], int) and r["rank"] > 0
                           else "notfound")
                    vals = (
                        r.get("id", ""), r["keyword"], r["domain"],
                        r["engine"], r["rank"], r["page"],
                        r["url"][:80] if r["url"] else "",
                        r["note"], r.get("submitted", ""),
                        r["checked_at"]
                    )
                    if self._tree.exists(row_id):
                        self._tree.item(row_id, tags=(tag,), values=vals)
                    self._progress_var.set(d["pct"])
                    self._lbl_progress.config(
                        text=f"{d['done']} / {d['total']}"
                    )
                    self._set_status(
                        f"[{r['engine']}] {r['keyword']} → 排名: {r['rank']}",
                        "running"
                    )

                elif msg == "done":
                    self._running = False
                    self._btn_start.config(state="normal",   bg="#dc2626")
                    self._btn_stop.config(state="disabled",  bg="#9ca3af")
                    found = sum(
                        1 for r in self._results
                        if isinstance(r["rank"], int) and r["rank"] > 0
                    )
                    self._set_status(
                        f"✅ 检测完成！共 {data} 条，找到排名 {found} 条",
                        "done"
                    )
                    close_all_drivers()

        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    # ── 表格操作 ─────────────────────────────────────────────

    def _prefill_table(self):
        for item in self._tree.get_children():
            self._tree.delete(item)
        engines = [k for k, v in self._engine_vars.items() if v.get()]
        if not engines:
            engines = ["google"]
        for item in self._keywords:
            for eng in engines:
                row_id    = f"{item['id']}_{eng}"
                eng_label = ENGINE_META[eng][0]
                self._tree.insert(
                    "", "end", iid=row_id,
                    values=(
                        item["id"], item["keyword"], item["domain"],
                        eng_label, "-", "-", "", "待检测", "-", ""
                    ),
                    tags=("",)
                )

    def _on_double_click(self, _event):
        sel = self._tree.selection()
        if not sel:
            return
        vals = self._tree.item(sel[0], "values")
        url = vals[6] if len(vals) > 6 else ""
        if url:
            self.clipboard_clear()
            self.clipboard_append(url)
            self._set_status(f"已复制 URL: {url[:60]}", "done")

    def _clear_results(self):
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._results.clear()
        self._progress_var.set(0)
        self._lbl_progress.config(text="0 / 0")
        self._set_status("已清空结果", "idle")
        logger.info("结果已清空")

    # ── 导出 ─────────────────────────────────────────────────

    def _export_csv(self):
        if not self._results:
            messagebox.showinfo("提示", "暂无结果"); return
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=f"seo_rank_{ts}.csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")]
        )
        if path:
            export_csv(self._results, path)
            self._set_status(f"CSV 已导出: {path}", "done")

    def _export_json(self):
        if not self._results:
            messagebox.showinfo("提示", "暂无结果"); return
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialfile=f"seo_rank_{ts}.json",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")]
        )
        if path:
            export_json(self._results, path)
            self._set_status(f"JSON 已导出: {path}", "done")

    # ── 关闭 ─────────────────────────────────────────────────

    def on_close(self):
        self._stop_event.set()
        logger.info("程序关闭，释放浏览器...")
        close_all_drivers()
        logger.info("再见！")
        self.destroy()


# ══════════════════════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════════════════════

def _open_path(path: str):
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# ══════════════════════════════════════════════════════════════
#  入口
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = SEOCheckerApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
