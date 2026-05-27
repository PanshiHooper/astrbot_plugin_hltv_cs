"""HLTV-CS Unified Plugin for AstrBot

统一CS2查询插件，整合以下功能：
  /match        — 查询CS2比赛（正在进行/已结束/即将开始）
  /player <名>  — 查询HLTV选手数据（Rating 3.0及分项）
  /team <战队>  — 查询HLTV战队信息（队员+近两年成绩）
  /team <战队> <地图> — 查询战队指定地图近3个月数据

数据来源：Liquipedia + HLTV
"""

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

from .core.http_client import set_request_delay
from .core.match_fetcher import MatchFetcher
from .core.player_lookup import lookup_player, lookup_player_trophies
from .core.team_lookup import lookup_team, lookup_team_map, ALIAS_TO_STANDARD


class HltvCsUnified(Star):
    """CS2 HLTV 统一查询插件"""

    MAX_INPUT_LENGTH = 100  # 选手/战队名最大长度

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}

        # ── 请求间隔 ──
        request_delay = float(self.config.get("request_delay", 1.5))
        set_request_delay(request_delay)

        cache_ttl = max(10, int(self.config.get("cache_ttl", 60)))
        use_hltv = bool(self.config.get("use_hltv", True))
        self._fetcher = MatchFetcher(cache_ttl=cache_ttl, use_hltv=use_hltv)
        self._extra_nicknames: dict = self._parse_nicknames(
            self.config.get("custom_nicknames", "")
        )

    async def terminate(self):
        """插件卸载/停用时关闭 HTTP 客户端"""
        await self._fetcher.close()

    @staticmethod
    def _parse_nicknames(raw: str) -> dict:
        """解析自定义外号文本（格式：外号=选手名，每行一个）"""
        result = {}
        if not raw or not raw.strip():
            return result
        for line in raw.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                nick, name = line.split("=", 1)
                nick = nick.strip()
                name = name.strip()
                if nick and name:
                    result[nick] = name
        return result

    @staticmethod
    def _get_command_args(event: AstrMessageEvent, command: str) -> str:
        """从原始消息中提取命令参数（/command 之后的所有文本）"""
        msg = event.message_str or ""
        # 去除可能的 platform 前缀如 /team 或 .team
        prefix = f"/{command}"
        if msg.startswith(prefix):
            return msg[len(prefix):].strip()
        # 也尝试不带 / 的
        if msg.startswith(command):
            return msg[len(command):].strip()
        return msg.strip()

    # ── /match ──────────────────────────────────────────────────────────

    @filter.command("match")
    async def cmd_match(self, event: AstrMessageEvent):
        """查询CS2今日比赛（进行中/已结束/即将开始）"""
        logger.info("/match 命令触发")
        result = await self._fetcher.fetch_matches()
        yield event.plain_result(result)

    # ── /player <选手名> [Trophies] ──────────────────────────────────

    @filter.command("player")
    async def cmd_player(self, event: AstrMessageEvent, player_name: str = ""):
        """查询HLTV CS2选手数据或荣誉

        /player <选手名>           → 选手 Rating 数据
        /player <选手名> Trophies  → 奖杯、MVP、EVP、Top20
"""
        # AstrBot 参数绑定可能只给第一个词，从原始消息补全
        full_args = self._get_command_args(event, "player")
        if full_args and (not player_name or len(full_args) > len(player_name)):
            player_name = full_args
        logger.info(f"/player 命令触发，参数: {player_name!r}")

        if not player_name:
            yield event.plain_result(
                "❌ 请提供选手名称或外号。\n\n"
                "查询数据: /player <选手名>\n"
                "示例: /player ZywOo\n"
                "      /player 载物\n\n"
                "查询荣誉: /player <选手名> Trophies\n"
                "示例: /player ZywOo Trophies\n"
                            )
            return

        if len(player_name) > self.MAX_INPUT_LENGTH:
            yield event.plain_result(
                f"❌ 输入过长（>{self.MAX_INPUT_LENGTH}字符），请缩短后重试。"
            )
            return

        # 检测是否包含 Trophies 关键词
        args_lower = player_name.lower().strip()
        parts = player_name.strip().split()

        if args_lower.endswith(" trophies") and len(parts) >= 2:
            pn = " ".join(parts[:-1])
            logger.info(f"荣誉查询: 选手={pn!r}")
            result = await lookup_player_trophies(pn, self._extra_nicknames)
            yield event.plain_result(result)
            return

        # 默认: 选手数据查询
        result = await lookup_player(player_name, self._extra_nicknames)
        yield event.plain_result(result)

    # ── /team <战队名> [地图名] ────────────────────────────────────────

    @filter.command("team")
    async def cmd_team(self, event: AstrMessageEvent, team_name: str = ""):
        """查询HLTV战队信息或地图统计

        /team <战队名>          → 战队总览（队员、胜率、成绩）
        /team <战队名> <地图名>  → 指定地图近3个月详细统计
        """
        # AstrBot 参数绑定可能只给第一个词，从原始消息补全
        full_args = self._get_command_args(event, "team")
        if full_args and (not team_name or len(full_args) > len(team_name)):
            team_name = full_args

        logger.info(f"/team 命令触发，参数: {team_name!r}")

        if not team_name:
            yield event.plain_result(
                "❌ 请提供战队名。\n\n"
                "查询战队: /team <战队名>\n"
                "示例: /team G2\n\n"
                "查询地图统计: /team <战队名> <地图名>\n"
                "示例: /team G2 inferno\n"
                "      /team falcons dust2\n"
                "      /team navi 小镇"
            )
            return

        if len(team_name) > self.MAX_INPUT_LENGTH:
            yield event.plain_result(
                f"❌ 输入过长（>{self.MAX_INPUT_LENGTH}字符），请缩短后重试。"
            )
            return

        # 检测是否包含地图名
        parts = team_name.strip().split()
        if len(parts) >= 2:
            # 从末尾向前尝试匹配地图名
            for i in range(len(parts) - 1, 0, -1):
                candidate_map = " ".join(parts[i:])
                if candidate_map.lower().strip() in ALIAS_TO_STANDARD:
                    tn = " ".join(parts[:i])
                    mn = candidate_map
                    logger.info(f"检测到地图查询: 战队={tn!r} 地图={mn!r}")
                    result = await lookup_team_map(tn, mn)
                    yield event.plain_result(result)
                    return

        # 普通战队查询
        result = await lookup_team(team_name)
        yield event.plain_result(result)
