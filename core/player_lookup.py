"""Player lookup - 从 HLTV 查询 CS2 选手详细数据

独立于框架，提供 async lookup_player() 函数。
"""

import re
import logging
from typing import Optional, Tuple

from bs4 import BeautifulSoup

from .http_client import fetch_page

logger = logging.getLogger("hltv_cs_unified.player_lookup")

HLTV_SEARCH = "https://www.hltv.org/search?query="
HLTV_PLAYER = "https://www.hltv.org/player/"

BREAKDOWN_KEYS = [
    "Firepower",
    "Entrying",
    "Trading",
    "Opening",
    "Clutching",
    "Sniping",
    "Utility",
]

# 默认选手外号字典
DEFAULT_NICKNAMES: dict[str, str] = {
    "载物": "ZywOo",
    "薯薯": "ZywOo",
    "大番薯": "ZywOo",
    "简单": "s1mple",
    "森破": "s1mple",
    "老猪": "s1mple",
    "小孩": "m0NESY",
    "海参": "m0NESY",
    "尼公子": "NiKo",
    "虾哥": "NiKo",
    "电子哥": "electroNic",
    "电子": "electroNic",
    "披肩": "donk",
    "洞主": "donk",
    "狂哥": "YEKINDAR",
    "寒王": "frozen",
    "魔男": "Magisk",
    "阿杜": "dupreeh",
    "阿汤": "device",
    "设备": "device",
    "表哥": "huNter-",
    "总监": "Twistzz",
    "鸡哥": "EliGE",
    "大壮": "blameF",
    "点哥": "ropz",
    "箱子": "ropz",
    "大光头": "karrigan",
    "西兰花": "broky",
    "西兰花花": "broky",
    "雨神": "rain",
    "垃圾话": "apEX",
    "豆豆": "apEX",
    "阿乐": "Aleksib",
    "阳光": "syrsoN",
    "狠人": "Ax1Le",
    "霍师傅": "HObbit",
    "若子": "sh1ro",
    "细弱": "sh1ro",
    "乐": "b1t",
    "B1T": "b1t",
    "P元帅": "Perfecto",
    "宙斯": "Zeus",
    "大表哥": "karrigan",
    "阿米": "NAF",
    "托哥": "torzsi",
    "太阳神": "suNny",
    "光头": "Snappi",
    "小吉米": "Jimpphat",
    "谢逊": "jL",
    "冥王": "Hobbit",
    "英雄": "Heroic",
    "非子": "fame",
    "老队长": "cadiaN",
    "点子": "cadiaN",
    "魔弟": "Magisk",
    "米神": "michu",
    "小蜜蜂": "Vitality",
    "萨尔瓦多": "arT",
    "回旋镖": "Boombl4",
    "胖球": "Boombl4",
}


def _resolve_nickname(raw_input: str, extra_nicknames: Optional[dict] = None) -> str:
    """通过外号字典解析选手名"""
    key = raw_input.strip().lower()
    resolved = DEFAULT_NICKNAMES.get(key)
    if resolved:
        logger.info(f"外号「{raw_input}」→ 选手「{resolved}」")
        return resolved
    if extra_nicknames:
        ekey = extra_nicknames.get(raw_input) or extra_nicknames.get(key)
        if ekey:
            logger.info(f"自定义外号「{raw_input}」→ 选手「{ekey}」")
            return ekey
    return raw_input


async def _search_player(name: str) -> Optional[Tuple[str, str]]:
    """在 HLTV 搜索选手，返回 (player_id, display_name)"""
    url = f"{HLTV_SEARCH}{name}"
    try:
        html = await fetch_page(url)
    except Exception as exc:
        logger.error(f"搜索失败: {exc!r}")
        return None

    soup = BeautifulSoup(html, "html.parser")

    for table in soup.find_all("table"):
        for row in table.select("tr"):
            cols = row.select("td")
            if not cols:
                continue
            link = row.select_one("a[href*='/player/']")
            if link:
                href = link.get("href", "")
                m = re.search(r"/player/(\d+)/", href)
                if m:
                    player_id = m.group(1)
                    display_name = link.get_text(strip=True)
                    return (player_id, display_name)

    all_links = soup.select("a[href*='/player/']")
    for link in all_links:
        href = link.get("href", "")
        m = re.search(r"/player/(\d+)/", href)
        text = link.get_text(strip=True)
        if m and text:
            return (m.group(1), text)

    logger.warning("搜索结果中未找到选手链接")
    return None


def _parse_player_stats(soup: BeautifulSoup, display_name: str) -> dict:
    """解析选手页面数据"""
    stats: dict = {
        "name": display_name,
        "rating": "",
        "breakdown": {},
        "all_time": {},
        "period": "",
        "age": "",
        "team": "",
        "prize_money": "",
    }

    # 年龄
    age_row = soup.select_one("div.playerInfoRow.playerAge")
    if age_row:
        age_val = age_row.select_one("div.listRight") or age_row.select_one("span.listRight")
        stats["age"] = age_val.get_text(strip=True) if age_val else ""

    # 当前战队
    team_row = soup.select_one("div.playerInfoRow.playerTeam")
    if team_row:
        team_val = team_row.select_one("div.listRight") or team_row.select_one("span.listRight")
        stats["team"] = team_val.get_text(strip=True) if team_val else ""

    # 奖金
    money_row = soup.select_one("div.playerInfoRow.playerPrizeMoney")
    if money_row:
        money_val = money_row.select_one("div.listRight") or money_row.select_one("span.listRight")
        stats["prize_money"] = money_val.get_text(strip=True) if money_val else ""

    stat_divs = soup.select("div.player-stat")
    for div in stat_divs:
        label_b = div.select_one("b")
        val_span = div.select_one("span.statsVal")
        if label_b and val_span:
            label = label_b.get_text(strip=True)
            if "rating" in label.lower():
                stats["rating"] = val_span.get_text(strip=True)
                break

    for div in stat_divs:
        top = div.select_one("div.player-stat-top")
        if not top:
            continue
        label_b = top.select_one("b")
        val_span = top.select_one("span.statsVal")
        if label_b and val_span:
            label = label_b.get_text(strip=True)
            if label in BREAKDOWN_KEYS:
                value_text = val_span.get_text(strip=True)
                stats["breakdown"][label] = value_text

    window_span = soup.select_one("span.stats-window")
    if window_span:
        stats["period"] = window_span.get_text(strip=True)

    highlighted = soup.select_one("div.highlighted-stats-box")
    if highlighted:
        stat_els = highlighted.select("div.all-time-stat")
        for el in stat_els:
            full_text = el.get_text(" ", strip=True)
            parts = full_text.split(None, 1)
            if len(parts) >= 2:
                key = parts[1].strip()
                val = parts[0].strip()
                stats["all_time"][key] = val

    return stats


def _bar_length(value: str) -> int:
    """将 Rating 值映射到 0-10 的条形长度"""
    try:
        num = int(value.split("/")[0]) if "/" in value else float(value)
        return max(0, min(10, round(num / 10)))
    except (ValueError, TypeError):
        return 0


def _format_stats(stats: dict) -> str:
    """格式化选手数据为文本"""
    lines = []
    name = stats.get("name", "Unknown")
    age = stats.get("age", "")
    team = stats.get("team", "")
    prize = stats.get("prize_money", "")

    lines.append(f"🎮 {name} 选手数据")

    # 基本信息行
    info_parts = []
    if age:
        info_parts.append(f"年龄: {age}")
    if team:
        info_parts.append(f"战队: {team}")
    if info_parts:
        lines.append("  " + " | ".join(info_parts))
    if prize:
        lines.append(f"  总奖金: {prize}")
    lines.append("")

    rating = stats.get("rating", "")
    period = stats.get("period", "")
    if rating:
        header = f"📊 Rating 3.0: {rating}"
        if period:
            header += f" {period}"
        lines.append(header)
        lines.append("")

    bd = stats.get("breakdown", {})
    if bd:
        lines.append("📈 Rating Breakdown")
        max_label = max(len(k) for k in bd.keys()) if bd else 10
        for key in BREAKDOWN_KEYS:
            val = bd.get(key, "-")
            if val != "-":
                num = _bar_length(val)
                bar = "█" * num + "░" * (10 - num)
                lines.append(f"{key:<{max_label}} [{bar}] {val}")
        lines.append("")

    all_time = stats.get("all_time", {})
    if all_time:
        lines.append("📋 全时期统计")
        for key, val in all_time.items():
            lines.append(f"  • {key}: {val}")

    return "\n".join(lines)


async def lookup_player(
    player_name: str,
    extra_nicknames: Optional[dict] = None,
) -> str:
    """查询 HLTV 选手数据，返回格式化文本

    Args:
        player_name: 选手名或外号
        extra_nicknames: 额外的外号映射字典

    Returns:
        格式化的选手数据文本
    """
    player_name = _resolve_nickname(player_name, extra_nicknames)
    logger.info(f"查询选手: {player_name}")

    # 1. 搜索选手
    search_result = await _search_player(player_name)
    if not search_result:
        return f"❌ 未找到选手「{player_name}」，请检查名称后重试。"

    player_id, display_name = search_result
    logger.info(f"找到选手: {display_name} (ID: {player_id})")

    # 2. 获取选手页面
    try:
        slug = display_name.replace(" ", "-").replace("'", "").lower()
        html = await fetch_page(f"{HLTV_PLAYER}{player_id}/{slug}")
    except Exception as exc:
        logger.error(f"获取选手页面失败: {exc!r}")
        return "❌ 获取选手数据失败，请稍后重试。"

    soup = BeautifulSoup(html, "html.parser")

    # 3. 解析数据
    stats = _parse_player_stats(soup, display_name)

    # 4. 格式化输出
    if not stats.get("rating"):
        return f"❌ 未能解析选手「{display_name}」的数据，HLTV 页面结构可能已更新。"

    return _format_stats(stats)


# ═══════════════════════════════════════════════════════════════════════
#  Trophies / MVPs / EVPs / Top20
# ═══════════════════════════════════════════════════════════════════════

async def lookup_player_trophies(
    player_name: str,
    extra_nicknames: Optional[dict] = None,
    mode: str = "all",
) -> str:
    """查询选手的奖杯、MVP、EVP、Top20 等荣誉数据

    Args:
        player_name: 选手名或外号
        extra_nicknames: 额外外号映射
        mode: "all"（Trophies+MVPs+Top20）或 "evps"（仅 EVPs）

    Returns:
        格式化的荣誉数据文本
    """
    player_name = _resolve_nickname(player_name, extra_nicknames)
    logger.info(f"查询选手荣誉: {player_name} mode={mode}")

    # 搜索选手
    search_result = await _search_player(player_name)
    if not search_result:
        return f"❌ 未找到选手「{player_name}」，请检查名称后重试。"

    player_id, display_name = search_result
    logger.info(f"找到选手: {display_name} (ID: {player_id})")

    # 获取选手页面
    try:
        slug = display_name.replace(" ", "-").replace("'", "").lower()
        html = await fetch_page(f"{HLTV_PLAYER}{player_id}/{slug}")
    except Exception as exc:
        logger.error(f"获取选手页面失败: {exc!r}")
        return "❌ 获取选手数据失败，请稍后重试。"

    soup = BeautifulSoup(html, "html.parser")

    if mode == "evps":
        return _format_evps(soup, display_name)
    else:
        return _format_trophies_full(soup, display_name)


def _parse_trophies(soup: BeautifulSoup) -> tuple:
    """解析 Trophies 区域：返回 (major_count, notable_count, events)"""
    # 找到包含 "Trophy overview" 的 trophy-section
    section = None
    for s in soup.select("div.trophy-section"):
        text = s.get_text(strip=True)[:200]
        if "trophy overview" in text.lower():
            section = s
            break

    if not section:
        return (0, 0, [])

    import re

    summary = section.get_text(strip=True)[:300]
    major_match = re.search(r"(\d+)\s*Major trophies", summary)
    notable_match = re.search(r"(\d+)\s*Notable trophies", summary)
    major_count = int(major_match.group(1)) if major_match else 0
    notable_count = int(notable_match.group(1)) if notable_match else 0

    # 读取奖杯事件列表（跳过 Top20、Awards 行）
    events = []
    skip_keywords = ("best player in", "player of the year", "awper of the year",
                     "highlight of the year", "rookie of the year",
                     "igl of the year", "coach of the year",
                     "women's player of the year")
    for row in section.select(".trophy-row"):
        event_el = row.select_one("div.trophy-event")
        if event_el:
            name = event_el.get_text(strip=True)
            if any(kw in name.lower() for kw in skip_keywords):
                continue
            if name and name not in events:
                events.append(name)

    return (major_count, notable_count, events)


def _parse_mvps(soup: BeautifulSoup) -> tuple:
    """解析 MVPs 区域：返回 (major_count, total_count, events)"""
    import re
    for section in soup.select("div.mvp-section"):
        text = section.get_text(strip=True)
        if "mvp overview" in text.lower():
            major_match = re.search(r"(\d+)\s*Major MVPs", text)
            total_match = re.search(r"(\d+)\s*Total MVPs", text)
            major_count = int(major_match.group(1)) if major_match else 0
            total_count = int(total_match.group(1)) if total_match else 0

            events = []
            for row in section.select(".trophy-row"):
                event_el = row.select_one("div.trophy-event")
                if event_el:
                    name = event_el.get_text(strip=True)
                    if name and name not in events:
                        events.append(name)

            return (major_count, total_count, events)

    return (0, 0, [])


def _parse_evps(soup: BeautifulSoup) -> tuple:
    """解析 EVPs 区域：返回 (major_count, total_count, events)"""
    import re
    for section in soup.select("div.mvp-section"):
        text = section.get_text(strip=True)
        if "evp overview" in text.lower():
            major_match = re.search(r"(\d+)\s*Major EVPs", text)
            total_match = re.search(r"(\d+)\s*Total EVPs", text)
            major_count = int(major_match.group(1)) if major_match else 0
            total_count = int(total_match.group(1)) if total_match else 0

            events = []
            for row in section.select(".trophy-row"):
                event_el = row.select_one("div.trophy-event")
                if event_el:
                    name = event_el.get_text(strip=True)
                    if name and name not in events:
                        events.append(name)

            return (major_count, total_count, events)

    return (0, 0, [])


def _parse_top20(soup: BeautifulSoup) -> list:
    """解析 HLTV Top 20 排名"""
    rankings = []
    import re
    for el in soup.select(".trophy-event"):
        text = el.get_text(strip=True)
        m = re.match(r"#(\d+)\s+best player in (\d+)", text, re.I)
        if m:
            rank = int(m.group(1))
            year = int(m.group(2))
            rankings.append((rank, year))
    # 去重并按年份降序
    seen = set()
    unique = []
    for r in sorted(rankings, key=lambda x: x[1], reverse=True):
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return unique


def _format_trophies_full(soup: BeautifulSoup, name: str) -> str:
    """格式化 Trophies + MVPs + Top20 输出"""
    lines = [f"🏆 {name} 荣誉总览\n"]

    # ── Trophies ──
    t_major, t_notable, t_events = _parse_trophies(soup)
    if t_events:
        lines.append(f"🥇 团队奖杯: {t_major} Major + {t_notable} 重要赛事")
        for ev in t_events:
            lines.append(f"  • {ev}")
        lines.append("")

    # ── MVPs ──
    m_major, m_total, m_events = _parse_mvps(soup)
    if m_events:
        lines.append(f"⭐ MVP 奖章: {m_major} Major MVP + 共 {m_total} 个")
        for ev in m_events:
            lines.append(f"  • {ev}")
        lines.append("")

    # ── EVPs ──
    e_major, e_total, e_events = _parse_evps(soup)
    if e_events:
        lines.append(f"📌 EVP 记录: {e_major} Major EVP + 共 {e_total} 个")
        for ev in e_events:
            lines.append(f"  • {ev}")
        lines.append("")

    # ── Top 20 ──
    top20 = _parse_top20(soup)
    if top20:
        lines.append("📊 HLTV Top 20 排名:")
        for rank, year in top20:
            medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else "  "
            lines.append(f"  {medal} #{rank} — {year}")
        lines.append("")

    if not any([t_events, m_events, e_events, top20]):
        return f"❌ 未能解析选手「{name}」的荣誉数据。"

    return "\n".join(lines)


def _format_evps(soup: BeautifulSoup, name: str) -> str:
    """格式化 EVPs 输出"""
    lines = [f"🏅 {name} EVP 荣誉\n"]

    e_major, e_total, e_events = _parse_evps(soup)
    if e_events:
        lines.append(f"📌 EVP 记录: {e_major} Major EVP + 共 {e_total} 个")
        for ev in e_events:
            lines.append(f"  • {ev}")
        lines.append("")
    else:
        lines.append("📌 该选手暂无 EVP 记录。")

    return "\n".join(lines)
