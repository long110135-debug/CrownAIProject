"""
皇冠AI赛事研判系统 - 基础抓取器
提供HTTP请求、重试、限速等通用能力
"""
import time
import random
import requests
from typing import Optional
from utils.logger import log

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False


class BaseScraper:
    """基础网页抓取器"""

    def __init__(self, config: dict = None):
        self.config = config or {
            "timeout": 15,
            "retry_count": 3,
            "retry_delay": 2,
            "request_interval": 1.5,
            "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
        }
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.config["user_agent"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        self._last_request_time = 0

    def _wait_interval(self):
        """请求间隔限速"""
        elapsed = time.time() - self._last_request_time
        interval = self.config["request_interval"] + random.uniform(0, 0.5)
        if elapsed < interval:
            time.sleep(interval - elapsed)
        self._last_request_time = time.time()

    def fetch(self, url: str, params: dict = None,
              headers: dict = None) -> Optional[str]:
        """带重试的GET请求"""
        self._wait_interval()
        retry_count = self.config.get("retry_count", 3)
        retry_delay = self.config.get("retry_delay", 2)
        timeout = self.config.get("timeout", 15)

        for attempt in range(retry_count):
            try:
                resp = self.session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=timeout,
                )
                resp.encoding = resp.apparent_encoding or "utf-8"
                if resp.status_code == 200:
                    return resp.text
                else:
                    log.warning(f"HTTP {resp.status_code}: {url} (尝试 {attempt+1}/{retry_count})")
            except requests.exceptions.Timeout:
                log.warning(f"请求超时: {url} (尝试 {attempt+1}/{retry_count})")
            except requests.exceptions.ConnectionError:
                log.warning(f"连接失败: {url} (尝试 {attempt+1}/{retry_count})")
            except Exception as e:
                log.warning(f"请求异常: {url} - {e} (尝试 {attempt+1}/{retry_count})")

            if attempt < retry_count - 1:
                time.sleep(retry_delay * (attempt + 1))

        log.error(f"抓取失败(已重试{retry_count}次): {url}")
        return None

    def fetch_json(self, url: str, params: dict = None) -> Optional[dict]:
        """获取JSON响应"""
        self._wait_interval()
        try:
            resp = self.session.get(
                url,
                params=params,
                timeout=self.config.get("timeout", 15),
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            log.warning(f"JSON请求失败: {url} - {e}")
        return None

    def parse_html(self, html: str):
        """解析HTML为BeautifulSoup对象"""
        if not HAS_BS4:
            log.error("需要安装 beautifulsoup4: pip3 install beautifulsoup4")
            return None
        return BeautifulSoup(html, "html.parser")

    def close(self):
        """关闭会话"""
        self.session.close()
