# CHANGELOG

## 2026-07-29 上线前阻断检查 + 统一结算函数

### 为什么改
CrownAI_2.0上线前阻断检查，六项审计+修复。

### 改了啥(修复节)
1. **唯一亚盘结算函数** `utils/odds_math.py` `settle_asian_handicap(direction,handicap,scores)`+`hit_to_pnl`：
   支持win/half_win/push/half_loss/loss/invalid/no_bet，覆盖0~±2全盘口。
   legacy/consensus/普通推荐/报表PnL统一调用。删除settle.py旧`_direction_to_hit`/`_hit_to_pnl`。
   prediction_history新增hit_result列(详细结果)，整数hit向后兼容。
2. **ROI口径** `get_experiment_stats`分母bet_count=COUNT(pnl非NULL)已含push，口径正确，加注释明确。
   (错误仅在报告手动计算: 应除以总投注7含push, 非非push的5)
3. **观察期validation** settings.py: OBSERVATION_PHASE="validation", FORMAL_OBSERVATION_VERSIONS=[]。
   observation.py新增_formal_progress(仅统计FORMAL版本)，验证期正式进度恒0/300，新数据debug_sample不计入门槛。

### 审计节(只读结论，未改)
- **节二 handicap方向**: 确认仍是让球方机械映射(升盘→home/降盘→away/不变→line_favorite)，
  change_score/water_score传入未用。三场客让全机械away。输出多信号合成redesign(未实现,未调权重)。
- **节三 赔率来源**: 确认API-Football Asian Handicap市场decimal赔率,同线双边,单bookmaker(Bet365首选),
  3场来源确认无unknown。风险:bookmaker跨时间切换+最平衡线跳变。
- **节四 时间存储**: 全部17字段naive字符串,不满足timezone-aware标准,6比较点依赖隐含假设。阻断项,待架构决策。

### 测试
新增test_settlement.py(10测试,含8固定用例)。394测试全通过。
历史dry-run: 普通推荐2处draw修正(0→invalid), 影子0差异。

### 结论
CrownAI_2.0维持validation,正式观察期不开启。阻断项: handicap方向redesign+时间存储迁移。
本轮未改权重/门槛/未切换consensus线上。

---

## 2026-07-29 逻辑修订收尾 + 观察期重置（CrownAI_2.0）

### 为什么改
P0/P1修复后做四项收尾：(1)prediction_history.asian_open误存当前盘而非真开盘；(2)ai_referee方向票是多数票复制造成重复计票；(3)模型逻辑根本变更后旧观察期数据失效需重置；(4)原7/28复盘报告含多处口径错误需重生成。

### 改了啥
1. `pipeline/daily_run.py` save_prediction: asian_open改存`open_handicap`(真开盘)，asian_live存分析时盘口，开盘→分析时变化可追溯
2. `pipeline/recommender.py` `_consensus_direction` + `pipeline/daily_run.py` `_build_consensus_reason`: ai_referee退出方向投票(它是裁决模型，direction为四模型多数票复制，计入会重复放大多数派)；reason串中标注excluded_referee
3. `config/settings.py`: MODEL_VERSION 1.0→2.0，VERSION→Crown_v2.0.0
4. `pipeline/observation.py` + `utils/database.get_experiment_stats`: 观察期计数(样本/联赛/盘口类型/等级/影子实验)动态过滤当前MODEL_VERSION，版本升级即观察期自动重置；null_tracking/neutral_analysis保持全量(数据质量指标)
5. 测试: test_observation/test_shadow_experiment造数改用当前MODEL_VERSION，断言调整为版本过滤后口径

### 行为变化
- 观察期从0重新起算(CrownAI_2.0当前0/300)，旧1.0记录(25预测+24影子)保留为历史不计入
- consensus方向不再含ai_referee重复票
- 新分析记录asian_open=真开盘
- 7/28复盘报告重生成(修正版): 北京时间、真实赔率PnL(旧逻辑+0.58/新方向逻辑+0.23,非±1的+3.0)、legacy 0有效推荐、临场变盘为时区错觉

### 测试
384测试全通过。observe确认CrownAI_2.0计数归零、NULL追踪仍见全部61条历史。

---

## 2026-07-29 修复盘口方向语义错误（P0）

### 为什么改
数据口径审计发现：handicap_model和market_model用"低水方=被看好方"判断方向，对让球盘系统性错误。客让盘(如客让0.25)中受让方(主队)天然低水，模型误判direction=home，与盘口真实语义(客队让球=客热)完全相反。Hearts(客让0.25)模型判home，实际客队0-2大胜。market_model的trap/heat模块正确识别让球方，但flow/方向模块仍犯同错，自相矛盾。

### 改了啥
1. `utils/odds_math.py` 新增 `line_favorite(handicap)`（盘口线热门方唯一实现）：主让→home，客让→away，平手→neutral
2. `models/handicap_model.py` `_determine_direction` 重设优先级：
   - 升盘/降盘(变动方向)优先 —— 保留合法的市场动量信号(升盘→home,降盘→away)
   - 无变动时，让球盘以让球方为方向(修复核心：客让→away而非低水主队)
   - 平手盘无让球方→退回水位方向(合法，无结构性热门)
3. `models/market_model.py`:
   - `_analyze_heat`: heat_side用line_favorite，平手返回neutral(原来错误默认away)
   - `_determine_direction`: 无诱热时跟随让球方(heat_side)而非水位流向；诱热保留反向操作；平手退回flow

### 行为变化(单元验证)
- 客让0.25不变: home→**away**(修复核心) | 主让0.5: home | 降盘: away | 升盘: home | 平手看水位

### 重要:7/28回溯PnL变化(如实记录)
用修复后模型回算7/28已结算7场shadow:
- Hearts客让0.25: 旧home(loss)→新away(win) ✓ 修正了审计记录的唯一错误
- Shamrock客让0.25: 旧home(win)→新away(loss) ✗ 该场受让方home爆冷2-1赢
- Banfield客让0.25: 旧home(win)→新away(loss) ✗ 该场受让方home爆冷3-2赢
- 净PnL: 旧+3(4赢2走1输) → 新+1(3赢2走2输)

解读: 修复语义正确(客让盘应押让球方/热门)，但本周3场客让中2场爆冷(受让方赢)，旧错误逻辑(押受让方)恰好押中冷门。这是小样本偶然(67%爆冷率异常高)。热门大样本胜率通常高于受让方，修复期望更优，但需观察期(300场)验证，不以7场回溯否定语义正确的修复。

### 测试
384测试全通过(含原有升盘→home/降盘→away用例)。

---

## 2026-07-29 修复赔率格式混用（P0）

### 为什么改
数据口径审计发现：api-football源写入欧洲盘十进制赔率(1.3~2.7)到home_water/away_water/over_water/under_water，而crown_daemon源写入亚洲盘水位HK(0.7~1.2)，两格式混存同一字段无标记。实测1675条记录中亚洲盘1159条(69%)+欧洲盘482条(29%)。模型阈值按亚洲盘校准(market_model的`home_odds>1.0`诱热、`home_odds<0.85`降盘热门)，欧洲盘输入使这些绝对阈值判断系统性失真(十进制恒>1.0诱热恒触发、恒不<0.85)。

### 改了啥
1. `utils/odds_math.py` 新增 `decimal_to_hk_water(odds)`（欧洲盘→亚洲盘水位唯一实现）：
   - 原理: 十进制=本金+利润, 亚洲盘水位=仅利润, 故 HK水=十进制-1 (1.95→0.95)
   - 幂等保护: <1.3的值(已是亚洲盘)原样返回，分界依据实测(亚洲盘≤1.23, 欧洲盘≥1.3)
2. `scraper/crown_odds_collector.py` save_api_odds: 写入前对home_water/away_water/over_water/under_water四个字段调用decimal_to_hk_water归一化(api-football数据唯一写入咽喉)

### 行为变化
- 新写入的api-football记录统一为亚洲盘HK格式，与crown_daemon一致(验证: 1.96/1.75→0.96/0.75, over1.85→0.85)
- market_model绝对阈值判断恢复语义(诱热>1.0只对真正高水触发，降盘热门<0.85可触发)
- 方向判断(home/away)不受影响——基于水位差，格式平移不改变差值
- 大小球over/under也一并转换(crown的over_water实测0.91是HK，api的1.88是十进制)

### 注意(过渡态)
- 历史api记录仍为decimal，不回填(遵循不自动回填历史数据原则)
- 今日比赛timeline会出现decimal(旧)+HK(新)混合，仅影响水位shift的"水位异动"检测；该检测对crown_index评分无实质影响(水位异动与不变同为handicap_change=17.5)，方向判断格式无关，故过渡态低风险
- fetch_odds_for_fixture仍返回原始decimal(诚实)，转换在存储层save_api_odds做

### 测试
384测试全通过。decimal_to_hk_water 8用例全对。真实track验证新记录为HK格式。

---

## 2026-07-29 修复crown_index管线天花板（P1）

### 为什么改
数据口径审计发现：analyze_matches和prematch_analyze硬编码`change_type='不变'`/`open_handicap=''`/`over_under=''`喂给模型，导致handicap模型change_score恒=50、crown的handicap_change恒=17.5，管线天花板被锁死在72.5，A级门槛(≥75)永远不可达。即使赛前盘口真实升降盘，系统也视而不见。

### 改了啥
1. `pipeline/daily_run.py` 新增 `_build_odds_data(match_id)` 辅助函数：
   - 从odds_timeline取开盘(get_opening_odds)和最新(get_latest_odds)记录
   - 调用 `utils.odds_math.compute_change()`（升盘/降盘判断的唯一实现）计算真实change_type
   - 返回含真实open_handicap/current_handicap/change_type/over_under的odds_data
2. analyze_matches: 删除硬编码odds_data构造，改用 `_build_odds_data(match_id)`
3. prematch_analyze: 同样改用 `_build_odds_data`（在强制刷新盘口后调用，取最新变动）

### 行为变化
- 盘口真实升盘/降盘时，crown_index现在能正确升高突破75（验证：升盘0.25→84.7，升盘0.5→90.2）
- 盘口未变动的比赛仍为原分数（不变=17.5），不人为抬分
- "水位异动"（仅水位动、盘口线未动）对handicap_change评分等同"不变"，水位信号由water_change分量独立捕捉
- 未改任何模型权重、阈值、推荐方向（仅修复数据喂入）

### 注意
今晚赛事盘口暂未变动(open==current)，仍全C级——这是正确行为。A级推荐只在赛前出现真实盘口变动时产生。strength=50问题(另一P0)仍把strength_match压在≤10，当前现实天花板约86.5(升盘0.5时)。

### 测试
384测试全通过。_build_odds_data对真实timeline正确输出升盘/降盘/水位异动。

---

## 2026-07-29 修复时区BUG（P0）

### 为什么改
数据口径审计发现：sync_today()直接截取API-Football返回的UTC时间存入match_time，而系统其余所有时间戳（odds_timeline.record_time、closing_odds.closing_time、datetime.now()比较）均为CST(UTC+8)。8小时偏移导致：收盘锁定提前~8h触发；prematch窗口失效；复盘报告误判"临场变盘发生在开赛后"。

### 改了啥
`pipeline/daily_run.py` sync_today()：
- 旧：`kickoff = f['fixture']['date'][:16].replace('T', ' ')`（UTC原样）
- 新：`kickoff = client._format_time(f['fixture']['date'])`（UTC→CST +8h）

### 行为变化
- 新sync的比赛match_time将为北京时间（与record_time/closing_time一致）
- lock_closing_odds/prematch_analyze/analyze_matches的时间比较自动修正
- 旧数据不回填（仍为UTC），今日重新sync后覆盖
- 注意：CST跨日比赛（如UTC 18:45 = CST次日02:45）的match_id中date仍为sync当天，不影响结算

### 测试
384测试全通过。_format_time转换验证：UTC 18:45 → CST 02:45(+1d) ✓

---

## 2026-07-29 临场二次分析窗口

### 为什么改
7/28复盘发现：系统首次分析在开赛前2-6小时完成，3场比赛的临场变盘（Hearts升盘→客胜、Shamrock降盘→主胜）均发生在开赛前1小时内，系统完全错过。盘口临场变动方向与赛果高度一致，是极高价值信号。

### 改了啥
1. `pipeline/daily_run.py`: 新增 `prematch_analyze()` 函数（section 4.5）
   - 开赛前15~45分钟窗口内，对已有首次分析的比赛强制刷新盘口并重跑五模型
   - 结果写入 `prematch_*` 新列，不覆盖首次分析，不触碰结算字段
   - 同步更新影子实验的 `prematch_consensus` 列
   - 新增 `_prematch_refresh_odds()` 辅助函数

2. `utils/database.py`: 新增迁移 `_migrate_prematch_columns()`
   - prediction_history: +9列 (prematch_at/handicap/home_water/away_water/crown_index/recommend/strength_score/handicap_score/market_score)
   - recommendation_experiments: +3列 (prematch_consensus/prematch_consensus_reason/prematch_at)
   - 新增 `save_prematch_update()` 和 `save_prematch_experiment()` 函数

3. `scheduler.py`: 新增 `prematch` 命令，使用 `TaskLock("analyze")` 与常规分析互斥

4. `~/Library/LaunchAgents/com.crownai.prematch.plist`: 每15分钟触发一次

5. `tests/test_prematch.py`: 10个测试用例（迁移/写入/不覆盖/已结算跳过/窗口逻辑/调度集成）

6. `tests/test_crown_collector_normalization.py`: 修正瑞甲/瑞超映射测试（瑞典超级甲组联赛→瑞甲，非瑞超）

### 行为变化
- 每15分钟自动检查是否有比赛进入临场窗口
- 首次分析结果保持不变（prediction_history原有列不动）
- 临场数据作为独立快照存入prematch_*列，供后续对比"首次分析 vs 临场分析 vs 实际结果"
- 影子实验同时记录首次consensus和临场consensus，可分别统计胜率
- 与track/settle/close互斥（共用analyze锁），不会并发写入

### 测试
384测试全通过（原374 + 新增10）
