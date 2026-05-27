"""Team lookup - 从 HLTV 查询 CS2 战队信息

独立于框架，提供 async lookup_team() 函数。
"""

import re
import logging
from datetime import datetime
from typing import Optional
from urllib.parse import quote

from bs4 import BeautifulSoup

from .http_client import fetch_page

logger = logging.getLogger("hltv_cs_unified.team_lookup")

HLTV_BASE = "https://www.hltv.org"
HLTV_SEARCH = f"{HLTV_BASE}/search"

_CUTOFF_YEAR = datetime.now().year - 1
TWO_YEARS_AGO = datetime(_CUTOFF_YEAR, 1, 1)

_TIME_TRANS = [
    ("years", "年"),
    ("year", "年"),
    ("months", "个月"),
    ("month", "个月"),
    ("days", "天"),
    ("day", "天"),
]


def _medal(placement: str) -> str:
    p = placement.strip().lower()
    if p == "1st":
        return "🥇"
    if p == "2nd":
        return "🥈"
    if p in ("3rd",):
        return "🥉"
    return ""


async def _search_team(name: str) -> Optional[str]:
    """在 HLTV 搜索战队，返回战队页面 URL"""
    url = f"{HLTV_SEARCH}?query={quote(name)}"
    html = await fetch_page(url)
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.select("a[href]"):
        href = link.get("href", "")
        if "/team/" in href:
            if href.startswith("/"):
                return f"{HLTV_BASE}{href}"
            if href.startswith("http"):
                return href
    return None


def _parse_team_display_name(soup: BeautifulSoup) -> Optional[str]:
    for sel in [
        "h1.profile-team-name",
        "h1.team-name",
        "div.profile-team-name",
        "h1",
        ".team-header h1",
    ]:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            if text and len(text) < 80:
                return text
    title = soup.select_one("title")
    if title:
        m = re.match(
            r"(.+?)\s+(team|roster|overview|stats)",
            title.get_text(strip=True),
            re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()
    return None


def _parse_players(soup: BeautifulSoup) -> list[dict[str, str]]:
    table = soup.select_one("table.players-table")
    if not table:
        logger.warning("未找到 players-table")
        return []

    tbody = table.select_one("tbody")
    if not tbody:
        return []

    players: list[dict[str, str]] = []
    for row in tbody.select("tr"):
        tds = row.select("td")
        if len(tds) < 5:
            continue

        nick_el = tds[0].select_one("div.playersBox-playernick div.text-ellipsis")
        nickname = nick_el.get_text(strip=True) if nick_el else "?"

        status_el = tds[1].select_one("div.player-status")
        status_cn = "首发"
        if status_el:
            classes = status_el.get("class", [])
            if "player-benched" in classes:
                status_cn = "替补"
            elif "player-coach" in classes:
                status_cn = "教练"

        time_el = tds[2].select_one("div.players-cell")
        time_raw = time_el.get_text(" ", strip=True) if time_el else ""
        time_cn = _translate_time(time_raw)

        maps_el = tds[3].select_one("div.players-cell")
        maps_played = maps_el.get_text(strip=True) if maps_el else "?"

        rating_el = tds[4].select_one("div.rating-cell")
        if rating_el:
            rating_text = rating_el.get_text(strip=True)
            rating_text = re.sub(r"\*+", "", rating_text).strip()
        else:
            rating_text = "?"

        players.append(
            {
                "nickname": nickname,
                "status": status_cn,
                "time": time_cn,
                "maps": maps_played,
                "rating": rating_text,
            }
        )

    logger.info(f"解析到 {len(players)} 名队员")
    return players


def _translate_time(time_raw: str) -> str:
    if not time_raw:
        return "-"
    result = time_raw
    for en, cn in _TIME_TRANS:
        result = result.replace(en, cn)
    return re.sub(r"\s+", "", result)


def _parse_map_stats(soup: BeautifulSoup) -> list[dict[str, str]]:
    containers = soup.select("div.map-statistics-container")
    if not containers:
        logger.warning("未找到 map-statistics-container")
        return []

    result: list[dict[str, str]] = []
    for container in containers:
        mapname_el = container.select_one("div.map-statistics-row-map-mapname")
        win_el = container.select_one("div.map-statistics-row-win-percentage")
        if mapname_el and win_el:
            mapname = mapname_el.get_text(strip=True)
            win_pct = win_el.get_text(strip=True)
            result.append({"map": mapname, "win_rate": win_pct})

    logger.info(f"解析到 {len(result)} 张地图胜率")
    return result


def _parse_achievement_table(
    soup: BeautifulSoup, section_id: str
) -> list[dict[str, str]]:
    container = soup.select_one(f"#{section_id}") or soup.select_one(
        f'[id*="{section_id}"]'
    )
    if not container:
        logger.warning(f"未找到 #{section_id}")
        return []

    table = container.select_one("table.achievement-table")
    if not table:
        logger.warning(f"#{section_id} 中未找到表格")
        return []

    tbody = table.select_one("tbody")
    if not tbody:
        return []

    results: list[dict[str, str]] = []
    for row in tbody.select("tr.team"):
        placement_el = row.select_one("div.achievement")
        placement = placement_el.get_text(strip=True) if placement_el else "?"
        placement = _normalize_placement(placement)

        name_el = row.select_one("td.tournament-name-cell a")
        tournament = name_el.get_text(strip=True) if name_el else "?"

        year = _extract_year(tournament)
        results.append(
            {
                "placement": placement,
                "tournament": tournament,
                "year": year,
            }
        )

    last_known_year: Optional[int] = None
    for r in results:
        if r["year"] is not None:
            last_known_year = r["year"]
        elif last_known_year is not None:
            r["year"] = last_known_year

    results = [
        r for r in results if r["year"] is not None and r["year"] >= _CUTOFF_YEAR
    ]

    logger.info(f"#{section_id}: {len(results)} 个成就（>= {_CUTOFF_YEAR}）")
    return results


def _normalize_placement(raw: str) -> str:
    raw_lower = raw.lower()
    if raw_lower in ("1st", "won", "winner"):
        return "1st"
    if raw_lower in ("2nd", "runner-up", "runner-up"):
        return "2nd"
    if raw_lower == "3rd":
        return "3rd"
    if raw_lower in ("3-4th", "3-4"):
        return "3-4th"
    if raw_lower in ("stage 3", "legends"):
        return "Legends"
    return raw


def _extract_year(text: str) -> Optional[int]:
    m = re.search(r"(?:^|\s)(\d{4})(?:$|\s|\b)", text)
    if m:
        return int(m.group(1))
    return None


def _format_achievements(items: list[dict]) -> list[str]:
    formatted: list[str] = []
    for a in items:
        placement = a["placement"]
        tournament = a["tournament"]
        med = _medal(placement)
        line = f"  {med} {placement} - {tournament}"
        formatted.append(line)
    return formatted


async def lookup_team(team_name: str) -> str:
    """查询 HLTV 战队信息，返回格式化文本

    Args:
        team_name: 战队英文名（如 G2, NAVI, Vitality）

    Returns:
        格式化的战队信息文本
    """
    logger.info(f"查询战队: {team_name}")

    # 1. 搜索战队
    team_url = await _search_team(team_name)
    if not team_url:
        return f"❌ 未找到战队「{team_name}」，请确认英文名是否正确。"

    # 2. 获取战队详情页
    html = await fetch_page(team_url)
    soup = BeautifulSoup(html, "html.parser")

    # 3. 提取信息
    display_name = _parse_team_display_name(soup) or team_name
    players = _parse_players(soup)
    map_stats = _parse_map_stats(soup)
    major = _parse_achievement_table(soup, "majorAchievement")
    lan = _parse_achievement_table(soup, "lanAchievement")

    # 4. 格式化输出
    lines = [f"🔍 {display_name}\n"]

    # 队员
    if players:
        lines.append("👥 队员:")
        for p in players:
            lines.append(
                f"{p['nickname']}：身份为{p['status']}，"
                f"在队时长{p['time']}，"
                f"参赛地图{p['maps']}张，"
                f"Rating3.0评分为{p['rating']}。"
            )
    else:
        lines.append("👥 队员: 未能解析")

    # 地图胜率
    if map_stats:
        lines.append("\n🗺️ 各地图胜率（近3个月）:")
        for m in map_stats:
            lines.append(f"  {m['map']}: {m['win_rate']}")
    else:
        lines.append("\n🗺️ 各地图胜率: 未能解析")

    # Major 成绩
    if major:
        lines.append("\n🏆 Major 成绩:")
        lines.extend(_format_achievements(major))
    else:
        lines.append("\n🏆 Major 成绩: 未能解析")

    # LAN 成绩
    if lan:
        lines.append("\n🏆 近两年大赛成绩:")
        lines.extend(_format_achievements(lan))
    else:
        lines.append("\n🏆 近两年大赛成绩: 未能解析")

    lines.append(f"\n🔗 {team_url}")
    return "\n".join(lines)


# ── 地图名别名 ──────────────────────────────────────────────────────────

MAP_ALIASES: dict[str, str] = {
    # 标准名 → 标准名（用于规范化）
    "anubis": "Anubis",
    "nuke": "Nuke",
    "ancient": "Ancient",
    "dust2": "Dust2",
    "dust 2": "Dust2",
    "d2": "Dust2",
    "沙二": "Dust2",
    "mirage": "Mirage",
    "米垃圾": "Mirage",
    "荒漠": "Mirage",
    "inferno": "Inferno",
    "inf": "Inferno",
    "小镇": "Inferno",
    "train": "Train",
    "火车": "Train",
    "vertigo": "Vertigo",
    "殒命大厦": "Vertigo",
    "overpass": "Overpass",
    "op": "Overpass",
    "游乐园": "Overpass",
    "cache": "Cache",
    "叉车": "Cache",
    "cobblestone": "Cobblestone",
    "cbble": "Cobblestone",
    "古堡": "Cobblestone",
}

ALIAS_TO_STANDARD = {k.lower().strip(): v for k, v in MAP_ALIASES.items()}


def resolve_map_name(raw: str) -> str:
    """将用户输入的地图名（包括别名/中文）解析为标准 HLTV 地图名"""
    key = raw.lower().strip()
    return ALIAS_TO_STANDARD.get(key, raw.title())


# ── 地图详细统计解析 ───────────────────────────────────────────────────

async def lookup_team_map(team_name: str, map_name: str) -> str:
    """查询指定战队在指定地图上的近 3 个月统计数据

    Args:
        team_name: 战队英文名
        map_name:  地图名（支持别名，如 d2→Dust2, 小镇→Inferno）

    Returns:
        格式化的地图统计数据文本
    """
    from bs4 import BeautifulSoup

    resolved_map = resolve_map_name(map_name)
    logger.info(f"查询战队地图: {team_name} → {resolved_map}")

    # 1. 搜索战队
    team_url = await _search_team(team_name)
    if not team_url:
        return f"❌ 未找到战队「{team_name}」，请确认英文名是否正确。"

    # 2. 获取战队详情页
    html = await fetch_page(team_url)
    soup = BeautifulSoup(html, "html.parser")

    display_name = _parse_team_display_name(soup) or team_name

    # 3. 遍历所有地图统计容器，匹配目标地图
    containers = soup.select("div.map-statistics-container")
    logger.info(f"找到 {len(containers)} 个地图统计容器")

    matched = None
    for container in containers:
        mapname_el = container.select_one("div.map-statistics-row-map-mapname")
        if not mapname_el:
            continue
        page_map = mapname_el.get_text(strip=True)
        if page_map.lower() == resolved_map.lower():
            matched = container
            break

    if matched is None:
        # 列出可用地图
        available = []
        for container in containers:
            mn = container.select_one("div.map-statistics-row-map-mapname")
            if mn:
                available.append(mn.get_text(strip=True))
        avail_str = "、".join(available) if available else "无"
        return (
            f"❌ 战队「{display_name}」没有地图「{resolved_map}」的近 3 个月数据。\n"
            f"\n可用地图: {avail_str}"
        )

    # 4. 解析详细数据
    return _format_map_stats(matched, display_name, resolved_map)


def _format_map_stats(
    container,
    display_name: str,
    map_name: str,
) -> str:
    """将单个地图统计容器格式化为文本输出"""
    lines = [f"🗺️ {display_name} — {map_name}（近 3 个月）\n"]

    # ── 胜率 ──
    win_pct_el = container.select_one("div.map-statistics-row-win-percentage")
    win_pct = win_pct_el.get_text(strip=True) if win_pct_el else "?"

    # ── 胜负平 ──
    wdl_el = container.select_one(
        "div.map-statistics-extended-wdl, div.highlighted-stats-box"
    )
    if wdl_el:
        wdl_text = wdl_el.get_text(strip=True)
        # 格式: "5Win0Draws1Losses" → "5W 0D 1L"
        import re
        w = re.search(r"(\d+)\s*Win", wdl_text)
        d = re.search(r"(\d+)\s*Draw", wdl_text)
        l = re.search(r"(\d+)\s*Loss", wdl_text)
        wdl_clean = ""
        if w:
            wdl_clean += f"{w.group(1)}W "
        if d:
            wdl_clean += f"{d.group(1)}D "
        if l:
            wdl_clean += f"{l.group(1)}L"
        wdl_clean = wdl_clean.strip()
    else:
        wdl_clean = "?"

    lines.append(f"📊 胜率: {win_pct} | {wdl_clean}")
    lines.append("")

    # ── 综合统计 ──
    stat_items = []
    for stat_div in container.select("div.map-statistics-extended-general-stat"):
        text = stat_div.get_text(strip=True)
        stat_items.append(text)

    if stat_items:
        lines.append("📈 近 3 个月数据:")
        for item in stat_items:
            # 格式化: "Round win% after getting first kill83.3%" → 拆分 key + value
            import re
            m = re.match(r"(.+?)(\d+\.?\d*%?)$", item)
            if m:
                key = m.group(1).strip()
                val = m.group(2).strip()
                # 缩写关键指标
                key = key.replace("Round win% after getting first kill", "首杀后回合胜率")
                key = key.replace("Round win% after getting first death", "首死后回合胜率")
                key = key.replace("Pistolround win%", "手枪局胜率")
                lines.append(f"  • {key}: {val}")
            else:
                lines.append(f"  • {item}")
        lines.append("")

    # ── 最大胜负 ──
    highlights = container.select("div.map-statistics-extended-highlight-container")
    for h in highlights:
        header_el = h.select_one("div.map-statistics-extended-sub-header")
        if not header_el:
            continue
        header = header_el.get_text(strip=True)

        if "biggest win" in header.lower():
            team1_el = h.select_one("div.biggest-map-team-container.team1, div.biggest-map-team-container")
            team2_el = h.select_one("div.biggest-map-team-container.team2")
            score_el = h.select_one("div.biggest-map-score-container")
            if team2_el and score_el:
                opp = team2_el.get_text(strip=True)
                score = score_el.get_text(strip=True)
                won = h.select_one("div.biggest-map-score.biggest-map-won")
                lost = h.select_one("div.biggest-map-score.biggest-map-lost")
                if won and lost:
                    lines.append(f"🟢 最大胜利: vs {opp}  {won.get_text(strip=True)}:{lost.get_text(strip=True)}")

        elif "biggest loss" in header.lower():
            # Check if empty
            empty = h.select_one("div.biggest-map-empty")
            if empty:
                lines.append("🔴 最大失利: 近 3 个月无失利")
            else:
                opp_el = h.select_one("div.biggest-map-team-container.team2")
                score_el = h.select_one("div.biggest-map-score-container")
                if opp_el and score_el:
                    opp = opp_el.get_text(strip=True)
                    won = h.select_one("div.biggest-map-score.biggest-map-won")
                    lost = h.select_one("div.biggest-map-score.biggest-map-lost")
                    if won and lost:
                        lines.append(f"🔴 最大失利: vs {opp}  {lost.get_text(strip=True)}:{won.get_text(strip=True)}")

    # ── Veto 数据 ──
    veto_el = container.select_one("div.map-statistics-extended-highlight-veto-container")
    if veto_el:
        picks_el = veto_el.select_one("div.map-statistics-extended-highlight-veto")
        if picks_el:
            lines.append("")
            lines.append("📋 Veto 数据:")
            for v in veto_el.select("div.map-statistics-extended-highlight-veto"):
                lines.append(f"  • {v.get_text(strip=True)}")

    return "\n".join(lines)
