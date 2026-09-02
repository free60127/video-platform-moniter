# 全平台视频数据统计器（video-platform-moniter）

自动采集你发布在 **抖音 / 快手 / 腾讯视频号 / 小红书 / B站** 的视频数据（播放、点赞、评论、收藏、分享）与账号粉丝变化，提供本地网页看板。

- 数据来自**你自己的创作者中心后台**（浏览器登录态），不是公开接口爬虫
- 一键采集全部平台，SQLite 保存每次快照，可看涨粉趋势
- 独立本地服务（127.0.0.1:8766），不占用视频发布工具

## 功能

| 平台 | 作品数据 | 账号数据 |
| --- | --- | --- |
| 抖音 | 播放/点赞/评论/分享/收藏/完播率 | — |
| 快手 | 播放/点赞/评论 | — |
| 腾讯视频号 | —（首页概览） | 关注者、昨日净增关注/新增播放/新增互动/新增评论 |
| 小红书 | 观看/评论/点赞/收藏/分享 | 粉丝、关注、近7日曝光/观看/点赞/涨粉 |
| B站 | 播放/点赞/评论/收藏/分享（API） | 粉丝、累计播放/点赞等 |

> 说明：各平台页面结构会不定期改版，采集字段以实际快照为准；解析基于创作者中心页面文本，改版后可能需更新对应 `collector/*.py`。

## 安装

需要 Python 3.10+ 与 Google Chrome（或已装 chromium）。

```bash
pip install -r requirements.txt
playwright install chromium
```

## 获取登录态（cookie）

先给工具授权：运行 `login.py`，会弹出浏览器窗口，你扫码/登录自己的创作者账号，登录成功后关闭窗口即保存。

```bash
# 依次登录抖音 / 快手 / 视频号 / 小红书
python login.py douyin kuaishou tencent xiaohongshu
```

保存位置：`cookies/<platform>_uploader/account.json`（Playwright storage_state 格式）。

B站支持两种格式均可（storage_state 或 biliup 的 `cookie_info.cookies` 格式）。

> ⚠️ `cookies/` 目录不会被 git 提交（已在 .gitignore），请勿把登录态泄露到公开仓库。

## 使用

```bash
python app.py
```

浏览器打开 <http://127.0.0.1:8766>：

- 顶部：总粉丝 / 总播放 / 总点赞 / 作品总数
- 平台卡片：各平台粉丝、涨粉差、近7日/昨日概览
- 作品明细表：每条视频的播放/点赞/评论/收藏/分享
- 「立即采集」按钮手动刷新；服务每 6 小时检查一次，距上次采集超过 20 小时自动采集

也可以纯命令行采集：

```bash
python -m collector                # 全部平台
python -m collector douyin xhs     # 指定平台（douyin|kuaishou|tencent|xiaohongshu|bilibili）
```

## 目录结构

```
app.py                 Flask 看板服务（127.0.0.1:8766）
login.py               登录态采集工具（浏览器扫码并保存 cookie）
collector/
  __init__.py          采集统一入口（run_all / run_platform）
  base.py              公共工具（cookie 读取、数字解析）
  douyin.py            抖音：创作者中心作品管理
  kuaishou.py          快手：作品管理列表
  tencent.py           腾讯视频号：首页概览（关注者/昨日数据）
  xiaohongshu.py       小红书：笔记管理（新版）/new/note-manager + 首页概览
  bilibili.py          B站：member API（archives + view/stat，纯 requests 无需浏览器）
store.py               SQLite 快照库（作品表 + 粉丝表，支持涨粉差分）
templates/index.html   网页看板
stats.db               本地 SQLite 数据库（自动创建，不入库）
```

## 部署为定时任务

`app.py` 内部自带每日自动采集（距上次 >20 小时触发）。若要固定时间：

```
# Windows 计划任务示例（每天 08:00 采集）
schtasks /create /tn "vpm-collect" /tr "python D:\path\to\stats-platform\collector" /sc daily /st 08:00
```

## 免责声明

- 本工具仅访问**你自己的账号后台**数据，用于内容运营分析
- 频繁采集可能触发平台风控，建议每天 1 次
- 因平台改版导致解析失效时，请更新对应 collector 或提交 issue
