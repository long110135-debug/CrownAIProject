"""
皇冠AI赛事研判系统 - 皇冠盘口抓取器 (Playwright版)
通过无头浏览器登录hga050.com，遍历早盘联赛，提取完整盘口数据

流程:
1. 登录(预设cookie跳过4pwd弹窗)
2. 等待SPA加载
3. 点击"早盘"导航
4. 遍历所有联赛，逐个点击提取盘口
5. 解析DOM文本为结构化数据
"""
import re
import json
import time
from datetime import datetime
from typing import List, Optional
from utils.logger import log

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False


# 目标联赛关键词(用于过滤)
TARGET_LEAGUES = [
    '英格兰超级联赛', '英格兰冠军联赛',
    '西班牙甲组联赛', '西班牙乙组联赛',
    '意大利甲组联赛', '意大利乙组联赛',
    '德国甲组联赛', '德国乙组联赛',
    '法国甲组联赛', '法国乙组联赛',
    '荷兰甲组联赛', '荷兰乙组联赛',
    '葡萄牙超级联赛', '葡萄牙甲组联赛',
    '阿根廷职业联赛',
    '瑞典超级联赛', '瑞典超级甲组联赛',
    '挪威超级联赛',
    '丹麦超级联赛', '丹麦甲组联赛',
    '芬兰超级联赛',
    '韩国', '日本',
    '美国', '墨西哥超级联赛',
    '巴西', '智利', '哥伦比亚',
    '土耳其', '俄罗斯', '瑞士超级联赛',
    '比利时', '苏格兰', '奥地利',
    '欧洲冠军联赛', '欧足联欧洲联赛',
]


class CrownOddsScraper:
    """皇冠盘口抓取器(Playwright版)"""

    def __init__(self, username: str, password: str, mid: str = ''):
        if not HAS_PLAYWRIGHT:
            raise ImportError("需要安装playwright: pip3 install playwright && python3 -m playwright install chromium")
        self.username = username
        self.password = password
        self.mid = mid
        self.page = None
        self.browser = None
        self.context = None
        self._pw = None

    def scrape_all_early(self, target_leagues: List[str] = None) -> List[dict]:
        """
        抓取所有早盘联赛的盘口数据

        返回: [{league, date, time, home, away, handicap, home_water, away_water,
                over_line, over_water, under_water, home_win, draw, away_win}]
        """
        leagues = target_leagues or TARGET_LEAGUES
        all_matches = []

        try:
            self._start_browser()
            self._login()
            self._wait_spa_ready()
            self._navigate_to_early()

            # 获取联赛列表
            league_list = self._get_league_list()
            log.info(f"[皇冠] 早盘联赛列表: {len(league_list)}个")

            # 过滤目标联赛
            target_found = []
            for lg in league_list:
                for kw in leagues:
                    if kw in lg['name']:
                        target_found.append(lg)
                        break

            log.info(f"[皇冠] 目标联赛: {len(target_found)}个")
            for lg in target_found:
                log.info(f"  - {lg['name']} ({lg['count']}场)")

            # 逐个联赛抓取
            for lg in target_found:
                try:
                    matches = self._scrape_league(lg)
                    all_matches.extend(matches)
                    log.info(f"[皇冠] {lg['name']}: {len(matches)}场")
                except Exception as e:
                    log.warning(f"[皇冠] {lg['name']} 抓取失败: {e}")
                    self._back_to_league_list()

            log.info(f"[皇冠] 总计抓取: {len(all_matches)}场")

        except Exception as e:
            log.error(f"[皇冠] 抓取异常: {e}")
        finally:
            self._close_browser()

        return all_matches

    def scrape_single_league(self, league_keyword: str) -> List[dict]:
        """抓取单个联赛的盘口数据"""
        try:
            self._start_browser()
            self._login()
            self._wait_spa_ready()
            self._navigate_to_early()

            league_list = self._get_league_list()
            target = None
            for lg in league_list:
                if league_keyword in lg['name']:
                    target = lg
                    break

            if not target:
                log.warning(f"[皇冠] 未找到联赛: {league_keyword}")
                return []

            matches = self._scrape_league(target)
            log.info(f"[皇冠] {target['name']}: {len(matches)}场")
            return matches

        except Exception as e:
            log.error(f"[皇冠] 抓取异常: {e}")
            return []
        finally:
            self._close_browser()

    # === 内部方法 ===

    def _start_browser(self):
        """启动无头浏览器"""
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(
            headless=True,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
        )
        self.context = self.browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='zh-CN',
            viewport={'width': 1280, 'height': 900},
        )
        # 反检测
        self.context.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined});')
        # 预设cookie跳过4pwd弹窗
        self.context.add_cookies([
            {'name': f'box4pwd_notshow_{self.mid}', 'value': f'{self.mid}_Y', 'domain': '.hga050.com', 'path': '/'},
        ])
        self.page = self.context.new_page()

    def _login(self):
        """登录皇冠"""
        log.info("[皇冠] 登录中...")
        self.page.goto('https://hga050.com', wait_until='domcontentloaded', timeout=30000)
        try:
            self.page.wait_for_selector('#usr', timeout=20000)
        except Exception:
            time.sleep(10)

        time.sleep(2)
        self.page.fill('#usr', self.username)
        self.page.fill('#pwd', self.password)
        time.sleep(1)
        self.page.click('#btn_login')

        # 等待登录成功
        for i in range(20):
            time.sleep(2)
            try:
                has_uid = self.page.evaluate('() => { try { return !!(top.userData && top.userData.uid); } catch(e) { return false; } }')
                if has_uid:
                    log.info("[皇冠] 登录成功")
                    return
            except Exception:
                pass

        raise Exception("登录超时")

    def _wait_spa_ready(self):
        """等待SPA主页加载"""
        log.info("[皇冠] 等待SPA加载...")
        for i in range(25):
            time.sleep(2)
            try:
                body = self.page.evaluate('() => document.body ? document.body.innerText : ""')
                if '早盘' in body and '滚球' in body:
                    log.info(f"[皇冠] SPA就绪 ({i*2}s)")
                    time.sleep(2)
                    return
            except Exception:
                pass
        raise Exception("SPA加载超时")

    def _navigate_to_early(self):
        """通过SPA内部路由导航到早盘联赛列表"""
        log.info("[皇冠] 导航到早盘...")

        # 方法1: 通过SPA内部事件系统导航(最可靠)
        self.page.evaluate('''() => {
            // 先点击左侧栏早盘按钮
            var el = document.getElementById('h_ft_early_league');
            if (el) el.click();
            // 通过SPA内部路由触发联赛列表加载
            if (typeof parentClass !== 'undefined' && parentClass.dispatchEvent) {
                parentClass.dispatchEvent('bodyGoToPage', {
                    page: 'league_index',
                    gtype: 'ft',
                    showtype: 'early'
                });
            }
        }''')

        # 等待真正的联赛条目出现(id=league_数字)
        for i in range(20):
            time.sleep(2)
            try:
                has_leagues = self.page.evaluate('''() => {
                    var els = document.querySelectorAll('[id^=league_]');
                    for (var i = 0; i < els.length; i++) {
                        if (/^league_\\d+$/.test(els[i].id) && els[i].offsetHeight > 0) return true;
                    }
                    return false;
                }''')
                if has_leagues:
                    log.info(f"[皇冠] 联赛数据已加载 ({i*2}s)")
                    time.sleep(2)
                    return
            except Exception:
                pass

        # 方法2: 备用鼠标点击
        log.warning("[皇冠] JS导航超时，尝试鼠标点击...")
        self.page.mouse.click(327, 28)
        time.sleep(10)

    def _get_league_list(self) -> List[dict]:
        """获取早盘联赛列表(只匹配id=league_数字的真实联赛条目)"""
        leagues = self.page.evaluate('''() => {
            var results = [];
            var els = document.querySelectorAll('[id^=league_]');
            for (var i = 0; i < els.length; i++) {
                var el = els[i];
                // 只匹配 league_数字 格式(排除league_now, league_tab等导航元素)
                if (!/^league_\\d+$/.test(el.id)) continue;
                var rect = el.getBoundingClientRect();
                if (rect.height > 0 && rect.width > 0) {
                    var name = '';
                    var count = 0;
                    var spans = el.querySelectorAll('span');
                    for (var j = 0; j < spans.length; j++) {
                        var t = spans[j].textContent.trim();
                        if (t && isNaN(t) && t.length > 2) name = t;
                        if (t && !isNaN(t)) count = parseInt(t);
                    }
                    if (!name) name = el.textContent.trim().replace(/\\d+/g, '').trim();
                    if (name) {
                        results.push({
                            id: el.id,
                            name: name,
                            count: count,
                            x: rect.x + rect.width/2,
                            y: rect.y + rect.height/2
                        });
                    }
                }
            }
            return results;
        }''')
        return leagues

    def _remove_overlay(self):
        """移除遮罩层(div_cleandata会拦截所有点击事件)"""
        self.page.evaluate('''() => {
            var maintain = document.getElementById('maintain_show');
            if (maintain) maintain.style.display = 'none';
            var cleandata = document.getElementById('div_cleandata');
            if (cleandata) cleandata.style.display = 'none';
        }''')

    def _scrape_league(self, league: dict) -> List[dict]:
        """点击联赛并抓取盘口数据"""
        self._remove_overlay()
        self.page.mouse.click(league['x'], league['y'])
        time.sleep(12)

        # 滚动加载所有数据
        for scroll_y in [500, 1000, 1500, 2000, 0]:
            self.page.evaluate(f'() => {{ var el = document.getElementById("body_show"); if(el) el.scrollTop = {scroll_y}; }}')
            time.sleep(3)

        # 获取页面文本
        full_text = self.page.evaluate('() => document.body ? document.body.innerText : ""')

        # 解析比赛数据
        matches = self._parse_matches(full_text, league['name'])

        # 返回联赛列表
        self._back_to_league_list()

        return matches

    def _back_to_league_list(self):
        """返回联赛列表页(浏览器后退+验证)"""
        try:
            self.page.go_back(wait_until='domcontentloaded', timeout=15000)
            time.sleep(5)

            # 验证是否回到联赛列表
            for i in range(10):
                time.sleep(2)
                try:
                    has_leagues = self.page.evaluate('''() => {
                        var els = document.querySelectorAll('[id^=league_]');
                        for (var i = 0; i < els.length; i++) {
                            if (/^league_\\d+$/.test(els[i].id) && els[i].offsetHeight > 0) return true;
                        }
                        return false;
                    }''')
                    if has_leagues:
                        self._remove_overlay()
                        return
                except Exception:
                    pass

            # 后退失败，重新导航
            log.warning("[皇冠] 后退未回到联赛列表，重新导航...")
            self._navigate_to_early()
        except Exception as e:
            log.warning(f"[皇冠] 返回联赛列表失败: {e}")
            time.sleep(3)

    def _parse_matches(self, text: str, league_name: str) -> List[dict]:
        """从页面文本解析比赛盘口数据"""
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        matches = []
        i = 0

        while i < len(lines):
            # 检测时间行: "08月21日 15:00"
            time_m = re.match(r'(\d{2}月\d{2}日)\s+(\d{2}:\d{2})', lines[i])
            if time_m:
                match = {
                    'league': league_name,
                    'date': time_m.group(1),
                    'time': time_m.group(2),
                    'home': '',
                    'away': '',
                    'handicap': '',
                    'home_water': '',
                    'away_water': '',
                    'over_line': '',
                    'over_water': '',
                    'under_water': '',
                    'home_win': '',
                    'draw': '',
                    'away_win': '',
                    'scrape_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }

                j = i + 1
                # 提取主队名
                skip_words = ('让球', '大/小', '独赢', '上半场', '开球', '波胆', '主要玩法', '让球&大小')
                if j < len(lines) and not re.match(r'^[\d.]+$', lines[j]) and len(lines[j]) < 25 and lines[j] not in skip_words:
                    match['home'] = lines[j]
                    j += 1
                # 提取客队名
                if j < len(lines) and not re.match(r'^[\d.]+$', lines[j]) and len(lines[j]) < 25 and lines[j] not in skip_words:
                    match['away'] = lines[j]
                    j += 1

                # 跳过投注数
                while j < len(lines) and re.match(r'^\d+$', lines[j]):
                    j += 1

                # 提取让球
                if j < len(lines) and lines[j] == '让球':
                    j += 1
                    if j < len(lines):
                        match['handicap'] = lines[j]
                        j += 1
                    if j < len(lines) and re.match(r'^[\d.]+$', lines[j]):
                        match['home_water'] = lines[j]
                        j += 1
                    # 客队让球(带+/-)
                    if j < len(lines) and re.match(r'^[+\-]', lines[j]):
                        j += 1
                    if j < len(lines) and re.match(r'^[\d.]+$', lines[j]):
                        match['away_water'] = lines[j]
                        j += 1

                # 提取大小球
                if j < len(lines) and lines[j] == '大/小':
                    j += 1
                    if j < len(lines) and lines[j] == '大':
                        j += 1
                    if j < len(lines):
                        match['over_line'] = lines[j]
                        j += 1
                    if j < len(lines) and re.match(r'^[\d.]+$', lines[j]):
                        match['over_water'] = lines[j]
                        j += 1
                    if j < len(lines) and lines[j] == '小':
                        j += 1
                    if j < len(lines):
                        j += 1  # skip line value
                    if j < len(lines) and re.match(r'^[\d.]+$', lines[j]):
                        match['under_water'] = lines[j]
                        j += 1

                # 提取独赢
                if j < len(lines) and lines[j] == '独赢':
                    j += 1
                    if j < len(lines) and lines[j] == '主':
                        j += 1
                    if j < len(lines) and re.match(r'^[\d.]+$', lines[j]):
                        match['home_win'] = lines[j]
                        j += 1
                    if j < len(lines) and lines[j] == '客':
                        j += 1
                    if j < len(lines) and re.match(r'^[\d.]+$', lines[j]):
                        match['away_win'] = lines[j]
                        j += 1
                    if j < len(lines) and lines[j] == '和':
                        j += 1
                    if j < len(lines) and re.match(r'^[\d.]+$', lines[j]):
                        match['draw'] = lines[j]
                        j += 1

                if match['home'] and match['away']:
                    matches.append(match)
                i = j
            else:
                i += 1

        return matches

    def _close_browser(self):
        """关闭浏览器"""
        try:
            if self.browser:
                self.browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass


def scrape_crown_odds(username: str, password: str, mid: str = '',
                      target_leagues: List[str] = None) -> List[dict]:
    """
    便捷函数: 抓取皇冠早盘盘口数据

    用法:
        matches = scrape_crown_odds('your_username', 'your_password')
        for m in matches:
            print(f"{m['home']} vs {m['away']} | 让球{m['handicap']} 主水{m['home_water']}")
    """
    scraper = CrownOddsScraper(username, password, mid)
    return scraper.scrape_all_early(target_leagues)
