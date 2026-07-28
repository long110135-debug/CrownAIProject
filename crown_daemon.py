#!/usr/bin/env python3
"""
皇冠AI赛事研判系统 - 皇冠盘口常驻守护进程
登录一次，浏览器保持打开，每N分钟刷新盘口数据。

优势:
- 不反复登录(皇冠登录慢且容易触发风控)
- 浏览器常驻，刷新盘口只需几秒
- 会话过期时自动重登

用法:
  python3 crown_daemon.py              前台运行(调试)
  python3 crown_daemon.py --interval 1800  自定义刷新间隔(秒)
"""
import sys
import os
import time
import json
import signal
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.logger import log

# === 配置 ===
REFRESH_INTERVAL = 1800  # 默认30分钟刷新一次
MAX_SESSION_HOURS = 6    # 最长保持6小时，之后主动重登(防风控)


class CrownDaemon:
    """皇冠盘口常驻守护进程"""

    def __init__(self, interval: int = REFRESH_INTERVAL):
        self.interval = interval
        self.browser = None
        self.page = None
        self.context = None
        self._pw = None
        self.logged_in = False
        self.login_time = None
        self.running = True
        self.scrape_count = 0

    def start(self):
        """启动守护进程"""
        log.info(f"[皇冠守护] 启动 (刷新间隔: {self.interval}s)")

        # 注册信号处理(优雅退出)
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        # 首次登录
        self._ensure_browser()

        # 主循环
        while self.running:
            try:
                self._scrape_cycle()
            except Exception as e:
                log.error(f"[皇冠守护] 抓取异常: {e}")
                # 异常后尝试重建浏览器
                self._cleanup_browser()
                time.sleep(30)
                self._ensure_browser()

            # 等待下次刷新
            self._sleep(self.interval)

        self._cleanup_browser()
        log.info("[皇冠守护] 已停止")

    def _scrape_cycle(self):
        """一次抓取周期"""
        # 检查会话是否需要刷新
        if self._need_relogin():
            log.info("[皇冠守护] 会话超时，重新登录...")
            self._cleanup_browser()
            time.sleep(5)
            self._ensure_browser()

        if not self.logged_in:
            log.warning("[皇冠守护] 未登录，等待下次重试")
            return

        # 刷新盘口数据
        from scraper.crown_scraper import CrownOddsScraper
        from scraper.crown_odds_collector import save_crown_odds
        try:
            matches = self._fetch_odds()
            if matches:
                save_crown_odds(matches, source="crown_daemon")
                self.scrape_count += 1
                log.info(f"[皇冠守护] 第{self.scrape_count}次抓取: {len(matches)}场")
            else:
                log.info("[皇冠守护] 本次无新数据")
        except Exception as e:
            log.warning(f"[皇冠守护] 抓取失败: {e}")
            # 可能是会话过期
            self.logged_in = False

    def _fetch_odds(self):
        """通过已登录的浏览器抓取盘口(复用现有CrownOddsScraper的解析逻辑)"""
        from scraper.crown_scraper import CrownOddsScraper, TARGET_LEAGUES

        if not self.page:
            return []

        try:
            all_matches = []

            # 抓取"今日"和"早盘"两个页面
            for showtype in ('today', 'early'):
                # 导航到对应联赛列表
                self.page.evaluate('''(showtype) => {
                    var el_id = showtype === 'today' ? 'h_ft_today_league' : 'h_ft_early_league';
                    var el = document.getElementById(el_id);
                    if (el) el.click();
                    if (typeof parentClass !== 'undefined' && parentClass.dispatchEvent) {
                        parentClass.dispatchEvent('bodyGoToPage', {
                            page: 'league_index', gtype: 'ft', showtype: showtype
                        });
                    }
                }''', showtype)
                time.sleep(8)

                # 移除遮罩
                self.page.evaluate('''() => {
                    var cleandata = document.getElementById('div_cleandata');
                    if (cleandata) cleandata.style.display = 'none';
                }''')

                # 获取联赛列表
                leagues = self.page.evaluate('''() => {
                var results = [];
                var els = document.querySelectorAll('[id^=league_]');
                for (var i = 0; i < els.length; i++) {
                    var el = els[i];
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
                        if (name) results.push({id: el.id, name: name, count: count,
                            x: rect.x + rect.width/2, y: rect.y + rect.height/2});
                    }
                }
                return results;
            }''')

                # 过滤目标联赛
                target = []
                for lg in leagues:
                    for kw in TARGET_LEAGUES:
                        if kw in lg['name']:
                            target.append(lg)
                            break

                if not target:
                    log.info(f"[皇冠守护] {showtype}: 无目标联赛")
                    continue

                log.info(f"[皇冠守护] {showtype}: 目标联赛{len(target)}个")

                # 逐联赛抓取
                for lg in target[:10]:  # 限制最多10个联赛(防超时)
                    try:
                        self.page.evaluate('''() => {
                            var cleandata = document.getElementById('div_cleandata');
                            if (cleandata) cleandata.style.display = 'none';
                        }''')
                        self.page.mouse.click(lg['x'], lg['y'])
                        time.sleep(10)

                        # 滚动加载
                        for sy in [500, 1000, 0]:
                            self.page.evaluate(f'() => {{ var el = document.getElementById("body_show"); if(el) el.scrollTop = {sy}; }}')
                            time.sleep(2)

                        text = self.page.evaluate('() => document.body ? document.body.innerText : ""')

                        # 用CrownOddsScraper的解析方法
                        scraper = CrownOddsScraper.__new__(CrownOddsScraper)
                        matches = scraper._parse_matches(text, lg['name'])
                        all_matches.extend(matches)

                        # 返回联赛列表
                        self.page.go_back(wait_until='domcontentloaded', timeout=15000)
                        time.sleep(4)
                    except Exception as e:
                        log.warning(f"[皇冠守护] {lg['name']} 抓取失败: {e}")
                        try:
                            self.page.go_back(wait_until='domcontentloaded', timeout=10000)
                            time.sleep(3)
                        except Exception:
                            pass

            return all_matches

        except Exception as e:
            log.error(f"[皇冠守护] 盘口抓取异常: {e}")
            return []

    def _ensure_browser(self):
        """确保浏览器已启动并登录"""
        if self.browser and self.logged_in:
            return

        try:
            from playwright.sync_api import sync_playwright
            from scraper.hga_scraper import get_hga_credentials

            user, pwd = get_hga_credentials()
            if not user or not pwd:
                log.error("[皇冠守护] 未配置皇冠账号")
                return

            # 启动浏览器
            if not self._pw:
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
            self.context.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined});')

            # 预设cookie跳过4pwd弹窗(MID从钥匙串读取)
            import subprocess as _sp
            try:
                mid = _sp.run(["security", "find-generic-password", "-s", "CrownAI_HGA_MID", "-w"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
            except Exception:
                mid = ''
            if mid:
                self.context.add_cookies([
                    {'name': f'box4pwd_notshow_{mid}', 'value': f'{mid}_Y', 'domain': '.hga050.com', 'path': '/'},
                ])

            self.page = self.context.new_page()

            # 登录
            log.info("[皇冠守护] 登录中...")
            self.page.goto('https://hga050.com', wait_until='domcontentloaded', timeout=30000)
            try:
                self.page.wait_for_selector('#usr', timeout=20000)
            except Exception:
                time.sleep(10)

            time.sleep(2)
            self.page.fill('#usr', user)
            self.page.fill('#pwd', pwd)
            time.sleep(1)
            self.page.click('#btn_login')

            # 等待登录成功
            for i in range(20):
                time.sleep(2)
                try:
                    has_uid = self.page.evaluate('() => { try { return !!(top.userData && top.userData.uid); } catch(e) { return false; } }')
                    if has_uid:
                        self.logged_in = True
                        self.login_time = datetime.now()
                        log.info("[皇冠守护] 登录成功，浏览器保持打开")
                        # 等待SPA加载
                        self._wait_spa()
                        return
                except Exception:
                    pass

            log.error("[皇冠守护] 登录超时")
            self._cleanup_browser()

        except Exception as e:
            log.error(f"[皇冠守护] 浏览器启动失败: {e}")
            self._cleanup_browser()

    def _wait_spa(self):
        """等待SPA主页加载"""
        for i in range(20):
            time.sleep(2)
            try:
                body = self.page.evaluate('() => document.body ? document.body.innerText : ""')
                if '早盘' in body and '滚球' in body:
                    log.info(f"[皇冠守护] SPA就绪 ({i*2}s)")
                    return
            except Exception:
                pass
        log.warning("[皇冠守护] SPA加载超时，继续尝试")

    def _need_relogin(self) -> bool:
        """检查是否需要重新登录"""
        if not self.logged_in:
            return True
        if not self.login_time:
            return True
        # 超过MAX_SESSION_HOURS主动重登
        elapsed = (datetime.now() - self.login_time).total_seconds() / 3600
        if elapsed > MAX_SESSION_HOURS:
            return True
        return False

    def _cleanup_browser(self):
        """关闭浏览器"""
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        self.browser = None
        self.page = None
        self.context = None
        self.logged_in = False
        self.login_time = None

    def _sleep(self, seconds: int):
        """可中断的等待"""
        end = time.time() + seconds
        while time.time() < end and self.running:
            time.sleep(5)

    def _handle_signal(self, signum, frame):
        """优雅退出"""
        log.info(f"[皇冠守护] 收到信号{signum}，准备退出...")
        self.running = False


if __name__ == "__main__":
    interval = REFRESH_INTERVAL
    if '--interval' in sys.argv:
        idx = sys.argv.index('--interval')
        if idx + 1 < len(sys.argv):
            interval = int(sys.argv[idx + 1])

    daemon = CrownDaemon(interval=interval)
    daemon.start()
