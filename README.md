# HLTV-CS 统一查询

AstrBot 插件，一站式查询 CS2 电竞资讯：比赛、选手、战队。

数据来源：Liquipedia + HLTV

## 更新说明
  5.27 叫AI修了点安全性问题 增加了返回列表，避免因为选手重名导致搜不到

## 命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `/match` | 查询今日 CS2 比赛（进行中 / 已结束 / 即将开始） | `/match` |
| `/player <名>` | 查询选手 Rating 3.0 数据、年龄、战队、奖金 | `/player donk` `/player 载物` |
| `/player <名> Trophies` | 查询选手奖杯、MVP、EVP、HLTV Top 20 排名 | `/player ZywOo Trophies` |
| `/team <战队>` | 查询战队队员名单、地图胜率、Major/LAN 成绩 | `/team G2` `/team NAVI` |
| `/team <战队> <地图>` | 查询战队在指定地图上的近 3 个月详细统计 | `/team G2 inferno` `/team falcons d2` |

`/player` 内置常用选手外号（载物 → ZywOo，森破 → s1mple，小孩 → m0NESY 等），也可在配置中自定义。

### 地图统计说明

使用 `/team <战队> <地图>` 可查询战队在指定地图上的近 3 个月数据，包括：

- 胜率与胜负场次（W/D/L）
- 首杀后回合胜率 / 首死后回合胜率 / 手枪局胜率
- 最大胜利 / 最大失利（对手及比分）
- Veto 数据（Pick / Ban 比例）

支持地图别名，方便输入：

| 别名 | 地图 |
|------|------|
| `d2`, `dust 2`, `沙二` | Dust2 |
| `inf`, `小镇` | Inferno |
| `米垃圾`, `荒漠` | Mirage |
| `op` | Overpass |
| `火车` | Train |
| `叉车` | Cache |
| `古堡` | Cobblestone |

标准英文名（Anubis、Nuke、Ancient、Vertigo 等）直接输入即可。

### 选手荣誉说明

使用 `/player <选手名> Trophies` 可查询选手的完整荣誉记录，包括：

- **团队奖杯**：Major 及重要赛事冠军（含次数统计）
- **MVP 奖章**：赛事 MVP（含 Major MVP 计数）
- **HLTV Top 20**：历年 HLTV 年度选手排名
- **EVP 记录**：赛事 Exceptional Valuable Player（含 Major EVP 计数）

示例输出：

```
🏆 ZywOo 荣誉总览

🥇 团队奖杯: 3 Major + 26 重要赛事
  • BLAST Rivals 2026 Season 1
  • IEM Rio 2026
  ...

⭐ MVP 奖章: 3 Major MVP + 共 32 个
  • StarLadder Budapest Major 2025
  • BLAST.tv Austin Major 2025
  ...

📊 HLTV Top 20 排名:
  🥇 #1 — 2025
  🥇 #1 — 2023
  ...
```

## 安装

将插件目录放入 AstrBot 的 `data/plugins/`：

```
data/plugins/
  astrbot_plugin_hltv_cs/
    ├── metadata.yaml
    ├── main.py
    └── ...
```

AstrBot 启动后会自动安装依赖（`requirements.txt`），无需手动 pip。

## 配置

在 AstrBot WebUI → 插件管理 → HLTV-CS 统一查询 → 配置：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | true | 是否启用插件 |
| `cache_ttl` | int | 60 | 比赛数据缓存时间（秒），降低可加快比分刷新 |
| `request_delay` | float | 1.5 | 请求间隔（秒），防止请求过快被网站限流，不建议低于 1.0 |
| `use_hltv` | bool | true | 是否启用 HLTV 补充数据（可补充 Liquipedia 遗漏的比赛） |
| `custom_nicknames` | text | (空) | 自定义选手外号，格式：`外号=选手名`，每行一个 |

自定义外号示例：

```
点子哥=cadiaN
阿汤哥=device
```

## 依赖

- `beautifulsoup4` — HTML 解析
- `httpx` — 异步 HTTP 客户端
- `curl_cffi`（可选）— 绕过 Cloudflare 防护，未安装时自动降级 httpx
- `lxml`（可选）— 高速 XML 解析器，未安装时回退 html.parser

## 数据说明

- 比赛数据从 [Liquipedia Counter-Strike](https://liquipedia.net/counterstrike/) 主页面抓取，HLTV API 补充遗漏的比赛
- 选手和战队数据从 [HLTV.org](https://www.hltv.org/) 页面解析
- 地图统计数据取自战队主页的地图统计面板（近 3 个月）
- 页面结构可能随网站更新而变化，如解析失败请提交 Issue

## 隐私说明

- 请求头使用通用 User-Agent（Linux x86_64 + Chrome），不包含操作系统或语言偏好的本机特征
- 所有 API 请求已添加内置速率限制，避免被目标站点封禁



## 致谢

作者PanshiHooper，由AI编写
