"""统一 HTTP 客户端

提供异步页面获取，优先使用 curl_cffi（可绕过 Cloudflare），
失败时降级到 httpx。
"""

import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger("hltv_cs_unified.http")

# ── 速率限制 ──
_request_lock = asyncio.Lock()
_last_request_time = 0.0
_request_delay: float = 1.5  # 默认 1.5 秒间隔


def set_request_delay(seconds: float) -> None:
    """设置两次请求之间的最小间隔（秒）"""
    global _request_delay
    _request_delay = max(0.0, seconds)
    logger.info(f"请求间隔已设为 {_request_delay}s")


async def _rate_limit() -> None:
    """必要时等待，以保证请求间隔"""
    global _last_request_time
    async with _request_lock:
        now = time.monotonic()
        elapsed = now - _last_request_time
        if elapsed < _request_delay:
            wait = _request_delay - elapsed
            logger.debug(f"速率限制：等待 {wait:.1f}s")
            await asyncio.sleep(wait)
        _last_request_time = time.monotonic()


# ── 请求头（已去除 OS / 语言特征）──
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

HEADERS_API = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Encoding": "gzip",
    "Accept-Language": "en-US,en;q=0.9",
}


async def fetch_page(
    url: str,
    impersonate: str = "chrome124",
    timeout: float = 15.0,
) -> Optional[str]:
    """异步获取页面 HTML。

    优先使用 curl_cffi（可绕过 Cloudflare 防护），
    失败或无此包时降级为 httpx。
    """

    await _rate_limit()

    # 优先 curl_cffi
    try:
        import importlib

        importlib.import_module("curl_cffi.requests")
        from curl_cffi.requests import AsyncSession

        async with AsyncSession(
            impersonate=impersonate,
            headers=HEADERS,
            timeout=timeout,
            verify=True,
        ) as session:
            resp = await session.get(url)
            if resp.status_code == 403:
                raise RuntimeError(f"{url} 返回 403 (Cloudflare 拦截)")
            resp.raise_for_status()
            logger.debug(f"curl_cffi {url} 成功 ({len(resp.text)} 字节)")
            return resp.text
    except ImportError:
        logger.debug("curl_cffi 未安装，降级 httpx")
    except Exception as exc:
        logger.warning(f"curl_cffi 失败: {exc!r}，降级 httpx")

    # 降级 httpx
    try:
        import httpx

        async with httpx.AsyncClient(
            headers=HEADERS,
            follow_redirects=True,
            timeout=httpx.Timeout(timeout),
        ) as client:
            resp = await client.get(url)
            if resp.status_code == 403:
                raise RuntimeError(f"{url} 返回 403 (Cloudflare 拦截)")
            resp.raise_for_status()
            logger.debug(f"httpx {url} 成功")
            return resp.text
    except Exception as exc:
        logger.error(f"httpx {url} 失败: {exc!r}")
        raise
