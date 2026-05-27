"""MatchFetcher - 从 Liquipedia 和 HLTV 获取 CS2 比赛数据

独立于框架，使用 httpx 进行异步网络请求。
"""

import re
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

import httpx

TZ_BEIJING = timezone(timedelta(hours=8))

DEFAULT_CACHE_TTL = 60
HLTV_API_URL = "https://www.hltv.org/api/matches"

HEADERS_LP = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

HEADERS_API = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
}

LIQUIPEDIA_MAIN = "https://liquipedia.net/counterstrike/Main_Page"
LIQUIPEDIA_API = "https://liquipedia.net/counterstrike/api.php"

PLACEHOLDER_TEAMS = frozenset({
    "tbd", "tba", "group a 1stplace", "group a 2ndplace", "group a 3rdplace",
    "group b 1stplace", "group b 2ndplace", "group b 3rdplace",
    "group c 1stplace", "group c 2ndplace", "group c 3rdplace",
    "group d 1stplace", "group d 2ndplace", "group d 3rdplace",
    "winner of", "loser of", "decider match winner",
})

PLACEHOLDER_KEYWORDS = ("1stplace", "2ndplace", "3rdplace", "4thplace", "5thplace")

logger = logging.getLogger("hltv_cs_unified.match_fetcher")

# ── 安全过滤 ──
import re as _re

_CONTROL_RE = _re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

def _sanitize(text: str) -> str:
    """移除控制字符，防止输出污染"""
    return _CONTROL_RE.sub("", text)


def _today_bounds_bj() -> Tuple[float, float]:
    """返回今天北京时间的起止Unix时间戳"""
    now_bj = datetime.now(TZ_BEIJING)
    start = datetime(now_bj.year, now_bj.month, now_bj.day, 0, 0, 0, tzinfo=TZ_BEIJING)
    end = start + timedelta(days=1)
    return start.timestamp(), end.timestamp()


class MatchFetcher:
    """从Liquipedia获取CS2比赛数据（HLTV补充）"""

    def __init__(self, cache_ttl: int = DEFAULT_CACHE_TTL, use_hltv: bool = True):
        self.cache_ttl = cache_ttl
        self.use_hltv = use_hltv
        self._client: Optional[httpx.AsyncClient] = None
        self._cache_soup = None
        self._cache_time = None
        self._cache_hltv = None
        self._cache_hltv_time = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=HEADERS_LP,
                timeout=20.0,
                follow_redirects=True,
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_matches(self) -> str:
        try:
            soup = await self._fetch_and_parse()
            if soup is None:
                return self._error_msg("无法连接到Liquipedia，请检查网络后重试。")
            matches = self._parse_matches(soup)
            matches = await self._merge_hltv(matches)
            return self._format_matches(matches)
        except Exception as e:
            logger.error(f"获取比赛数据失败: {e}", exc_info=True)
            return self._error_msg(
                f"获取比赛数据时出错: {str(e)}\n"
                "请稍后重试或访问 https://liquipedia.net/counterstrike/ 查看。"
            )

    def _error_msg(self, detail: str) -> str:
        return f"[ERR] {detail}"

    async def _fetch_and_parse(self):
        now_bj = datetime.now(TZ_BEIJING)
        if (
            self._cache_soup is not None
            and self._cache_time is not None
            and (now_bj - self._cache_time).total_seconds() < self.cache_ttl
        ):
            logger.info("使用缓存的比赛数据")
            return self._cache_soup

        from bs4 import BeautifulSoup

        client = await self._get_client()
        html_obj = None

        try:
            logger.info("尝试 Liquipedia API...")
            params = {
                "action": "parse",
                "page": "Main_Page",
                "format": "json",
                "prop": "text",
            }
            resp = await client.get(LIQUIPEDIA_API, params=params, headers=HEADERS_API)
            if resp.status_code == 200:
                data = resp.json()
                html_obj = data.get("parse", {}).get("text", {}).get("*", "")
                if html_obj:
                    logger.info(f"API 成功获取 {len(html_obj)} 字符")
            else:
                logger.warning(f"API 返回状态码: {resp.status_code}")
        except Exception as e:
            logger.warning(f"API 请求失败: {e}")

        if not html_obj:
            try:
                resp = await client.get(LIQUIPEDIA_MAIN)
                if resp.status_code == 200:
                    html_obj = resp.text
                else:
                    logger.warning(f"直接请求返回: {resp.status_code}")
            except Exception as e:
                logger.warning(f"直接请求失败: {e}")

        if not html_obj:
            return None

        parser = self._get_parser()
        soup = BeautifulSoup(html_obj, parser)
        self._cache_soup = soup
        self._cache_time = now_bj
        return soup

    @staticmethod
    def _get_parser() -> str:
        try:
            import lxml  # noqa: F401
            return "lxml"
        except ImportError:
            return "html.parser"

    def _parse_matches(self, soup) -> Dict[str, List[Dict]]:
        result = {"ongoing": [], "completed": [], "upcoming": []}
        now_ts = time.time()
        today_start, today_end = _today_bounds_bj()

        match_divs = soup.find_all("div", class_="match-info")
        logger.info(f"找到 {len(match_divs)} 个 match-info 元素")

        for div in match_divs:
            match_data = self._parse_match_info_div(div)
            if match_data is None:
                continue
            if self._is_full_placeholder(match_data):
                continue

            ts = match_data.get("timestamp", 0)
            finished = match_data.get("finished") == "finished"
            is_today = today_start <= ts < today_end if ts > 0 else False

            if finished:
                if is_today:
                    result["completed"].append(match_data)
            elif is_today and ts <= now_ts:
                result["ongoing"].append(match_data)
            elif ts > now_ts:
                if ts < today_end + 86400:
                    result["upcoming"].append(match_data)

        logger.info(
            f"解析结果: 进行中={len(result['ongoing'])}, "
            f"已结束={len(result['completed'])}, "
            f"即将开始={len(result['upcoming'])}"
        )
        return result

    @staticmethod
    def _is_full_placeholder(match_data: Dict) -> bool:
        t1 = match_data.get("team1", "").strip().lower()
        t2 = match_data.get("team2", "").strip().lower()
        t1_ph = (
            not t1
            or t1 in PLACEHOLDER_TEAMS
            or any(kw in t1 for kw in PLACEHOLDER_KEYWORDS)
        )
        t2_ph = (
            not t2
            or t2 in PLACEHOLDER_TEAMS
            or any(kw in t2 for kw in PLACEHOLDER_KEYWORDS)
        )
        return t1_ph and t2_ph

    @staticmethod
    def _normalize_team(name: str) -> str:
        n = name.strip().lower()
        if not n or n in PLACEHOLDER_TEAMS or any(kw in n for kw in PLACEHOLDER_KEYWORDS):
            return "TBD"
        return name.strip()

    @staticmethod
    def _clean_tournament_name(raw: str) -> str:
        if not raw:
            return ""
        name = raw.replace("/", " ").replace("#", " ")
        name = " ".join(name.split())
        if len(name) > 50:
            name = name[:47] + "..."
        return name

    async def _fetch_hltv_matches(self) -> Optional[List[Dict]]:
        now_bj = datetime.now(TZ_BEIJING)
        if (
            self._cache_hltv is not None
            and self._cache_hltv_time is not None
            and (now_bj - self._cache_hltv_time).total_seconds() < self.cache_ttl
        ):
            return self._cache_hltv

        try:
            client = await self._get_client()
            resp = await client.get(HLTV_API_URL, headers=HEADERS_API)
            if resp.status_code == 200:
                raw = resp.json()
                if isinstance(raw, list):
                    matches = []
                    now_ts = time.time()
                    for m in raw:
                        t1 = m.get("team1") or {}
                        t2 = m.get("team2") or {}
                        t1n = (
                            t1.get("teamNameLong")
                            or t1.get("teamNameShort")
                            or ""
                        ).strip()
                        t2n = (
                            t2.get("teamNameLong")
                            or t2.get("teamNameShort")
                            or ""
                        ).strip()
                        if (
                            not t1n
                            or not t2n
                            or t1n.lower() in ("no team", "tbd", "tba")
                        ):
                            continue
                        event = m.get("event_v2") or {}
                        if isinstance(event, dict):
                            ename = event.get("name", "")
                        else:
                            ename = str(m.get("event", ""))
                        ts = m.get("startDateTime", 0)
                        matches.append(
                            {
                                "team1": t1n,
                                "team2": t2n,
                                "event": ename,
                                "timestamp": ts,
                                "hltv_id": m.get("id"),
                            }
                        )
                    self._cache_hltv = matches
                    self._cache_hltv_time = now_bj
                    logger.info(f"HLTV获取 {len(matches)} 场比赛")
                    return matches
        except Exception as e:
            logger.warning(f"HLTV请求失败: {e}")
        return self._cache_hltv

    @staticmethod
    def _merge_team_name(name: str) -> str:
        n = name.strip().lower()
        n = re.sub(r"\(.*?\)", "", n)
        n = re.sub(r"\[.*?\]", "", n)
        n = re.sub(r"team\s+", "", n)
        n = re.sub(r"esports|gaming|clan", "", n)
        n = " ".join(n.split())
        return n

    async def _merge_hltv(self, matches: Dict) -> Dict:
        if not self.use_hltv:
            return matches

        hltv = await self._fetch_hltv_matches()
        if not hltv:
            return matches

        now_ts = time.time()
        today_start, today_end = _today_bounds_bj()

        def _make_key(t1, t2):
            return frozenset(
                [self._merge_team_name(t1), self._merge_team_name(t2)]
            )

        existing_keys = set()
        for cat in ("ongoing", "completed", "upcoming"):
            for m in matches[cat]:
                existing_keys.add(_make_key(m["team1"], m["team2"]))

        added = 0
        for hm in hltv:
            ts = hm["timestamp"]
            if ts <= 0 or ts >= today_end + 86400:
                continue
            if ts <= now_ts:
                continue
            key = _make_key(hm["team1"], hm["team2"])
            if key in existing_keys:
                continue
            existing_keys.add(key)
            matches["upcoming"].append(
                {
                    "team1": hm["team1"],
                    "team2": hm["team2"],
                    "score1": "-",
                    "score2": "-",
                    "tournament": self._clean_tournament_name(hm.get("event", "")),
                    "timestamp": ts,
                    "finished": "",
                    "source": "hltv",
                }
            )
            added += 1

        if added:
            logger.info(f"HLTV补充了 {added} 场即将开始的比赛")
        return matches

    def _parse_match_info_div(self, div) -> Optional[Dict]:
        try:
            opp_divs = div.find_all("div", class_="match-info-header-opponent")
            teams = []
            for opp in opp_divs:
                block = opp.find("div", class_="block-team")
                if block:
                    link = block.find("a")
                    name = (
                        link.get("title") or link.get_text(strip=True)
                    ) if link else block.get_text(strip=True)[:40]
                else:
                    name = opp.get_text(strip=True)[:40]
                teams.append(name)

            if len(teams) < 2:
                return None

            score_spans = div.find_all(
                "span", class_="match-info-header-scoreholder-score"
            )
            score1 = score_spans[0].get_text(strip=True) if score_spans else "-"
            score2 = (
                score_spans[1].get_text(strip=True) if len(score_spans) > 1 else "-"
            )

            timer_span = div.find("span", class_="timer-object")
            timestamp = 0
            finished = ""
            if timer_span:
                ts_raw = timer_span.get("data-timestamp")
                if ts_raw:
                    try:
                        timestamp = int(ts_raw)
                    except (ValueError, TypeError):
                        pass
                finished = timer_span.get("data-finished", "")

            tourney_div = div.find("div", class_="match-info-tournament")
            tournament = ""
            if tourney_div:
                link = tourney_div.find("a")
                tournament = (
                    link.get("title") or link.get_text(strip=True)
                ) if link else tourney_div.get_text(strip=True)[:50]

            return {
                "team1": teams[0],
                "team2": teams[1],
                "score1": score1,
                "score2": score2,
                "tournament": self._clean_tournament_name(tournament),
                "timestamp": timestamp,
                "finished": finished,
            }
        except Exception as e:
            logger.debug(f"解析 match-info div 失败: {e}")
            return None

    def _format_matches(self, matches: Dict) -> str:
        now_bj = datetime.now(TZ_BEIJING)
        today_str = now_bj.strftime("%m/%d")
        hour_str = now_bj.strftime("%H:%M")
        lines = [f"[CS2] CS2 今日比赛  ({today_str} {hour_str} BJT)\n"]

        if matches.get("ongoing"):
            lines.append("[LIVE] 正在进行")
            for m in matches["ongoing"]:
                t1 = self._normalize_team(m["team1"])
                t2 = self._normalize_team(m["team2"])
                t = f" | {m['tournament']}" if m.get("tournament") else ""
                lines.append(f"  {t1}  {m['score1']} : {m['score2']}  {t2}{t}")
            lines.append("")

        if matches.get("completed"):
            lines.append("[DONE] 今天已结束")
            for m in matches["completed"][:15]:
                t1 = self._normalize_team(m["team1"])
                t2 = self._normalize_team(m["team2"])
                t = f" | {m['tournament']}" if m.get("tournament") else ""
                lines.append(f"  {t1}  {m['score1']}:{m['score2']}  {t2}{t}")
            lines.append("")

        if matches.get("upcoming"):
            lines.append("[NEXT] 即将开始")
            for m in matches["upcoming"][:15]:
                t1 = self._normalize_team(m["team1"])
                t2 = self._normalize_team(m["team2"])
                t = f" | {m['tournament']}" if m.get("tournament") else ""
                ts = m.get("timestamp", 0)
                ts_str = ""
                if ts > 0:
                    dt = datetime.fromtimestamp(ts, tz=TZ_BEIJING)
                    ts_str = f" ({dt.strftime('%m/%d %H:%M')})"
                lines.append(f"  {t1}  vs  {t2}{t}{ts_str}")
            lines.append("")

        if not any(matches.values()):
            lines.append("[INFO] 当前暂无CS2比赛数据，请稍后重试。")
            lines.append(
                "  建议访问 https://liquipedia.net/counterstrike/ 直接查看。"
            )

        lines.append("\n[SRC] 数据来源: Liquipedia Counter-Strike")
        return _sanitize("\n".join(lines))
