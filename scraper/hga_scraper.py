"""
皇冠AI赛事研判系统 - 皇冠盘口抓取器 (requests轻量版)

定位: 登录/会话管理/健康检查
实际盘口数据抓取请使用 crown_scraper.py (Playwright版)

原因: hga050.com是SPA架构，盘口数据通过JS内部XHR加载，
纯HTTP请求无法获取。但登录接口(transform_nl.php p=chk_login)
可以通过requests完成。

API结构:
- 登录接口: POST /transform_nl.php (p=chk_login) ✓可用
- 数据接口: SPA内部XHR (需Playwright渲染) ✗纯requests不可用
- 首页: GET / → POST /(detection=Y) → 获取ver

账号密码存储在macOS钥匙串:
- 服务名: CrownAI_HGA_USER
- 服务名: CrownAI_HGA_PASS
"""
import re
import time
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Optional, Tuple
from utils.logger import log

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# === 皇冠站点配置 ===
HGA_CONFIG = {
    "base_url": "https://hga050.com",
    "api_endpoint": "/transform_nl.php",
    "login_endpoint": "/transform_nl.php",
    "langx": "zh-cn",
    "gtype_ft": "ft",  # 足球
    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "request_interval": 2.0,  # 请求间隔(秒)
    "timeout": 15,
}


def get_hga_credentials() -> Tuple[str, str]:
    """从macOS钥匙串获取皇冠账号密码"""
    user = _keychain_get("CrownAI_HGA_USER")
    pwd = _keychain_get("CrownAI_HGA_PASS")
    return user, pwd


def save_hga_credentials(username: str, password: str):
    """保存皇冠账号密码到macOS钥匙串"""
    _keychain_set("CrownAI_HGA_USER", username)
    _keychain_set("CrownAI_HGA_PASS", password)
    log.info("皇冠账号已保存到钥匙串")


def _keychain_get(service: str) -> str:
    """从钥匙串读取"""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _keychain_set(service: str, value: str):
    """写入钥匙串"""
    try:
        # 先删除旧的
        subprocess.run(
            ["security", "delete-generic-password", "-s", service],
            capture_output=True, timeout=5
        )
    except Exception:
        pass
    try:
        subprocess.run(
            ["security", "add-generic-password", "-s", service, "-a", "CrownAI", "-w", value],
            capture_output=True, timeout=5
        )
    except Exception as e:
        log.error(f"钥匙串写入失败: {e}")


class HGACrownScraper:
    """皇冠盘口抓取器 (hga050.com) - requests轻量版"""

    MAX_RETRIES = 3
    RETRY_BACKOFF = [2, 5, 10]  # 重试等待秒数

    def __init__(self):
        if not HAS_REQUESTS:
            log.error("需要安装requests: pip3 install requests")
            return

        self.config = HGA_CONFIG
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.config["user_agent"],
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": self.config["base_url"],
            "Origin": self.config["base_url"],
        })
        self.logged_in = False
        self.ver = ""  # 版本号(从首页获取)
        self._last_request = 0
        self._login_count = 0  # 登录次数(防无限重登)

    def login(self, username: str = None, password: str = None) -> bool:
        """
        登录皇冠平台
        
        如果不传参数，自动从钥匙串读取
        """
        if not username or not password:
            username, password = get_hga_credentials()

        if not username or not password:
            log.error("未配置皇冠账号。请运行: python3 setup_hga.py 设置账号密码")
            return False

        log.info(f"[皇冠] 正在登录... (用户: {username[:3]}***)")

        try:
            # Step 1: 访问首页获取ver和初始cookie
            self._init_session()

            # Step 2: 发送登录请求
            login_data = {
                "p": "chk_login",
                "langx": self.config["langx"],
                "ver": self.ver,
                "username": username,
                "password": password,
                "app": "N",
                "auto": "BZAFGI",
                "blackbox": "",
                "userAgent": self.config["user_agent"],
            }

            resp = self._post_raw(self.config["login_endpoint"], login_data)
            if not resp:
                log.error("[皇冠] 登录请求失败")
                return False

            # 解析登录响应
            if self._check_login_success(resp):
                self.logged_in = True
                self._login_count += 1
                log.info("[皇冠] 登录成功")
                return True
            else:
                log.error(f"[皇冠] 登录失败: {self._extract_error(resp)}")
                return False

        except Exception as e:
            log.error(f"[皇冠] 登录异常: {e}")
            return False

    def fetch_football_odds(self, showtype: str = "today") -> List[dict]:
        """
        获取足球盘口数据
        
        参数:
        - showtype: "today"(今日) / "early"(早盘) / "live"(滚球)
        
        返回: 比赛盘口列表
        """
        if not self._ensure_logged_in():
            return []

        log.info(f"[皇冠] 获取足球盘口 (showtype={showtype})...")

        params = {
            "p": "gameDate",
            "gtype": self.config["gtype_ft"],
            "showtype": showtype,
            "langx": self.config["langx"],
            "ver": self.ver,
        }

        resp = self._post(self.config["api_endpoint"], params)
        if not resp:
            return []

        matches = self._parse_game_xml(resp, showtype)
        log.info(f"[皇冠] 获取到 {len(matches)} 场足球比赛盘口")
        return matches

    def fetch_all_football(self) -> List[dict]:
        """
        一次性获取今日+早盘所有足球盘口(去重)
        
        返回: 合并后的比赛列表，每场标记showtype
        """
        all_matches = {}

        for showtype in ("today", "early"):
            try:
                odds_list = self.fetch_football_odds(showtype=showtype)
                for m in odds_list:
                    key = m.get("match_id") or f"{m.get('home_team')}_{m.get('away_team')}"
                    if key not in all_matches:
                        all_matches[key] = m
                time.sleep(1.5)
            except Exception as e:
                log.warning(f"[皇冠] {showtype}盘口获取失败: {e}")

        result = list(all_matches.values())
        log.info(f"[皇冠] 合计获取 {len(result)} 场(today+early去重)")
        return result

    def health_check(self) -> bool:
        """
        检查会话是否仍然有效
        
        注: 由于数据接口是SPA内部XHR，无法通过requests直接验证。
        此方法检查session cookie是否存在且logged_in标记有效。
        实际数据抓取请使用Playwright版(crown_scraper.py)。
        """
        if not self.logged_in:
            return False
        # 检查session是否有cookie
        if not self.session.cookies:
            self.logged_in = False
            return False
        return True

    def fetch_league_list(self, showtype: str = "today") -> List[dict]:
        """获取联赛列表"""
        if not self.logged_in:
            if not self.login():
                return []

        params = {
            "p": "leagueList",
            "gtype": self.config["gtype_ft"],
            "showtype": showtype,
            "langx": self.config["langx"],
            "ver": self.ver,
        }

        resp = self._post(self.config["api_endpoint"], params)
        if not resp:
            return []

        return self._parse_league_xml(resp)

    def fetch_match_detail(self, game_id: str) -> Optional[dict]:
        """获取单场比赛详细盘口（含初盘/即时盘变化）"""
        if not self.logged_in:
            if not self.login():
                return None

        params = {
            "p": "gameMore",
            "gtype": self.config["gtype_ft"],
            "game_id": game_id,
            "langx": self.config["langx"],
            "ver": self.ver,
        }

        resp = self._post(self.config["api_endpoint"], params)
        if not resp:
            return None

        return self._parse_detail_xml(resp)

    # === 内部方法 ===

    def _ensure_logged_in(self) -> bool:
        """确保已登录，会话过期时自动重连(最多重登2次)"""
        if self.logged_in:
            return True
        if self._login_count >= 3:
            log.error("[皇冠] 登录次数过多，停止重试")
            return False
        log.warning("[皇冠] 未登录/会话过期，尝试(重新)登录...")
        return self.login()

    def _init_session(self):
        """初始化会话，获取ver和cookie"""
        try:
            # Step 1: GET首页(获取初始cookie)
            self.session.get(
                self.config["base_url"],
                timeout=self.config["timeout"],
                allow_redirects=True,
            )

            # Step 2: POST detection(模拟首页JS的init()行为，获取ver)
            resp = self.session.post(
                self.config["base_url"],
                data={"detection": "Y", "sub_doubleLogin": "", "isapp": "", "q": "", "appversion": ""},
                timeout=self.config["timeout"],
                allow_redirects=True,
            )

            # 从响应中提取ver (格式: top.ver = 'hash_timestamp')
            ver_match = re.search(r"top\.ver\s*=\s*'([^']+)'", resp.text)
            if ver_match:
                self.ver = ver_match.group(1)
                log.info(f"[皇冠] 获取版本号: {self.ver[:30]}...")
            else:
                log.warning("[皇冠] 未获取到ver(可能影响后续请求)")
        except Exception as e:
            log.warning(f"[皇冠] 初始化会话异常: {e}")

    def _post_raw(self, endpoint: str, data: dict) -> Optional[str]:
        """发送单次POST请求(无重试)"""
        self._wait()
        url = self.config["base_url"] + endpoint
        try:
            resp = self.session.post(url, data=data, timeout=self.config["timeout"],
                                     allow_redirects=False)
            # 302重定向通常意味着会话过期
            if resp.status_code in (301, 302):
                log.warning(f"[皇冠] 重定向({resp.status_code})，会话可能过期")
                self.logged_in = False
                return None
            if resp.status_code == 200:
                resp.encoding = "utf-8"
                return resp.text
            else:
                log.warning(f"[皇冠] HTTP {resp.status_code}: {endpoint}")
                return None
        except requests.exceptions.Timeout:
            log.warning(f"[皇冠] 请求超时: {endpoint}")
            return None
        except Exception as e:
            log.warning(f"[皇冠] 请求异常: {e}")
            return None

    def _post(self, endpoint: str, data: dict) -> Optional[str]:
        """发送POST请求(带重试+指数退避+会话过期检测)"""
        for attempt in range(self.MAX_RETRIES):
            resp = self._post_raw(endpoint, data)
            if resp:
                return resp

            # 会话过期，尝试重登
            if not self.logged_in and attempt < self.MAX_RETRIES - 1:
                log.info(f"[皇冠] 第{attempt+1}次重试，尝试重新登录...")
                if not self.login():
                    break
                continue

            # 普通失败，等待后重试
            if attempt < self.MAX_RETRIES - 1:
                wait_sec = self.RETRY_BACKOFF[attempt]
                log.info(f"[皇冠] 第{attempt+1}次重试，等待{wait_sec}s...")
                time.sleep(wait_sec)

        return None

    def _wait(self):
        """请求限速"""
        elapsed = time.time() - self._last_request
        if elapsed < self.config["request_interval"]:
            time.sleep(self.config["request_interval"] - elapsed)
        self._last_request = time.time()

    def _check_login_success(self, resp: str) -> bool:
        """
        检查登录是否成功
        
        实际XML格式:
        成功: <serverresponse><status>ok</status>...<uid>xxx</uid>...</serverresponse>
        失败: <serverresponse><status>error</status><msg>101</msg>
              <code_message>密码错误次数过多...</code_message>...</serverresponse>
        """
        # 明确的错误状态
        if "<status>error</status>" in resp:
            return False
        # 成功: 有uid返回且非空
        uid_match = re.search(r"<uid>([^<]+)</uid>", resp)
        if uid_match and uid_match.group(1).strip():
            return True
        # 成功: status不是error
        if "<status>" in resp and "<status>error</status>" not in resp:
            return True
        return False

    def _extract_error(self, resp: str) -> str:
        """提取错误信息"""
        msg_match = re.search(r"<msg>([^<]*)</msg>", resp)
        code_msg_match = re.search(r"<code_message>([^<]*)</code_message>", resp)
        msg = msg_match.group(1) if msg_match else "?"
        code_msg = code_msg_match.group(1) if code_msg_match else ""
        if code_msg:
            return f"msg={msg} ({code_msg})"
        return f"msg={msg}"

    def _parse_game_xml(self, xml_text: str, showtype: str) -> List[dict]:
        """
        解析比赛列表XML
        
        皇冠XML结构(典型):
        <serverresponse>
            <code>200</code>
            <game>
                <ec>联赛ID</ec>
                <cn>联赛名</cn>
                <gn>比赛ID</gn>
                <hn>主队</hn>
                <an>客队</an>
                <st>开赛时间</st>
                <hdp>让球</hdp>
                <ho>主水</ho>
                <ao>客水</ao>
                <ou>大小球</ou>
                <oo>大球水</oo>
                <uo>小球水</uo>
                ...
            </game>
        </serverresponse>
        """
        matches = []

        try:
            # 清理可能的非法XML字符
            xml_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', xml_text)
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            # 尝试正则解析（皇冠有时返回非标准XML）
            return self._parse_game_regex(xml_text, showtype)

        # 遍历game节点
        for game in root.iter():
            if game.tag in ("game", "ec"):
                match = self._extract_game_node(game, showtype)
                if match:
                    matches.append(match)

        # 如果标准解析没结果，尝试正则
        if not matches:
            matches = self._parse_game_regex(xml_text, showtype)

        return matches

    def _extract_game_node(self, node, showtype: str) -> Optional[dict]:
        """从XML节点提取比赛数据"""
        def get_text(tag):
            el = node.find(tag)
            return el.text.strip() if el is not None and el.text else ""

        home = get_text("hn") or get_text("home")
        away = get_text("an") or get_text("away")
        if not home or not away:
            return None

        league = get_text("cn") or get_text("league") or ""
        game_id = get_text("gn") or get_text("gid") or ""
        match_time = get_text("st") or get_text("time") or ""

        # 盘口数据
        hdp = get_text("hdp") or get_text("handicap") or ""
        ho = get_text("ho") or get_text("home_odds") or ""
        ao = get_text("ao") or get_text("away_odds") or ""
        ou = get_text("ou") or get_text("overunder") or ""
        oo = get_text("oo") or get_text("over_odds") or ""
        uo = get_text("uo") or get_text("under_odds") or ""

        # 初盘（如果有）
        open_hdp = get_text("ohdp") or get_text("open_hdp") or hdp
        open_ho = get_text("oho") or get_text("open_ho") or ho
        open_ao = get_text("oao") or get_text("open_ao") or ao

        return {
            "match_id": f"HGA_{game_id}" if game_id else f"HGA_{home}_{away}",
            "game_id": game_id,
            "league": league,
            "home_team": home,
            "away_team": away,
            "match_time": match_time,
            "showtype": showtype,
            "opening": {
                "handicap": self._format_handicap(open_hdp, home),
                "home_water": self._safe_float(open_ho),
                "away_water": self._safe_float(open_ao),
            },
            "current": {
                "handicap": self._format_handicap(hdp, home),
                "home_water": self._safe_float(ho),
                "away_water": self._safe_float(ao),
            },
            "over_under": {
                "line": ou,
                "over_water": self._safe_float(oo),
                "under_water": self._safe_float(uo),
            },
            "source": "hga050",
            "scrape_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _parse_game_regex(self, text: str, showtype: str) -> List[dict]:
        """正则解析（备用方案，应对非标准XML）"""
        matches = []

        # 尝试匹配各种可能的数据格式
        # 格式1: JSON-like
        json_pattern = r'\{[^{}]*"hn"\s*:\s*"([^"]+)"[^{}]*"an"\s*:\s*"([^"]+)"[^{}]*\}'
        for m in re.finditer(json_pattern, text):
            matches.append({
                "match_id": f"HGA_{m.group(1)}_{m.group(2)}",
                "home_team": m.group(1),
                "away_team": m.group(2),
                "league": "",
                "showtype": showtype,
                "source": "hga050_regex",
            })

        # 格式2: 分隔符格式
        if not matches:
            # 皇冠有时用特殊分隔符
            lines = text.split("\n")
            for line in lines:
                if "|" in line and len(line.split("|")) > 5:
                    parts = line.split("|")
                    if len(parts) >= 8:
                        matches.append({
                            "match_id": f"HGA_{parts[0]}",
                            "game_id": parts[0],
                            "league": parts[1] if len(parts) > 1 else "",
                            "home_team": parts[2] if len(parts) > 2 else "",
                            "away_team": parts[3] if len(parts) > 3 else "",
                            "match_time": parts[4] if len(parts) > 4 else "",
                            "showtype": showtype,
                            "current": {
                                "handicap": parts[5] if len(parts) > 5 else "",
                                "home_water": self._safe_float(parts[6]) if len(parts) > 6 else 0,
                                "away_water": self._safe_float(parts[7]) if len(parts) > 7 else 0,
                            },
                            "source": "hga050_regex",
                        })

        return matches

    def _parse_league_xml(self, xml_text: str) -> List[dict]:
        """解析联赛列表"""
        leagues = []
        try:
            xml_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', xml_text)
            root = ET.fromstring(xml_text)
            for el in root.iter():
                if el.tag in ("ec", "league"):
                    name = ""
                    lid = ""
                    for child in el:
                        if child.tag in ("cn", "name"):
                            name = child.text or ""
                        if child.tag in ("ec", "id"):
                            lid = child.text or ""
                    if name:
                        leagues.append({"id": lid, "name": name})
        except ET.ParseError:
            pass
        return leagues

    def _parse_detail_xml(self, xml_text: str) -> Optional[dict]:
        """解析单场详细盘口"""
        try:
            xml_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', xml_text)
            root = ET.fromstring(xml_text)
            # 提取详细盘口变化
            detail = {"raw": xml_text[:500]}
            for el in root.iter():
                if el.tag == "game":
                    return self._extract_game_node(el, "detail")
            return detail
        except ET.ParseError:
            return {"raw": xml_text[:500]}

    def _format_handicap(self, hdp_value: str, home_team: str) -> str:
        """格式化盘口为中文"""
        if not hdp_value:
            return ""
        try:
            val = float(hdp_value)
            if val > 0:
                return f"主让{val}"
            elif val < 0:
                return f"客让{abs(val)}"
            else:
                return "平手"
        except ValueError:
            return hdp_value

    def _safe_float(self, val) -> float:
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    def close(self):
        """关闭会话"""
        self.session.close()
        self.logged_in = False


def quick_fetch_odds(target_leagues: List[str] = None) -> List[dict]:
    """
    便捷函数: 一次性获取皇冠所有足球盘口
    
    自动登录→获取today+early→关闭会话
    
    参数:
    - target_leagues: 可选，过滤联赛关键词列表(如['英超','西甲'])
    
    返回: 盘口列表
    """
    scraper = HGACrownScraper()
    try:
        if not scraper.login():
            return []
        matches = scraper.fetch_all_football()

        # 联赛过滤
        if target_leagues and matches:
            filtered = []
            for m in matches:
                league = m.get("league", "")
                if any(kw in league for kw in target_leagues):
                    filtered.append(m)
            matches = filtered

        return matches
    finally:
        scraper.close()
