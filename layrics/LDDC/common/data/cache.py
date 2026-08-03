# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only
"""Disk cache (slimmed from LDDC: cache dir moved to appdirs, no longer depends on common.paths)"""

import atexit
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, ParamSpec, TypeVar

import appdirs
from diskcache import Cache

_cache_dir = Path(appdirs.user_cache_dir("layrics")) / "lddc"
_cache_dir.mkdir(parents=True, exist_ok=True)
cache = Cache(_cache_dir, sqlitecache_size=512)
cache_version = 6
if "version" not in cache or cache["version"] != cache_version:
    cache.clear()
cache["version"] = cache_version

P = ParamSpec("P")
T = TypeVar("T")


def cached_call[**P, T](
    func: Callable[P, T],
    cache_settings: dict | None = None,
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """High-performance cached call with parameter filtering and type awareness.

    Args:
        func (Callable): the function to cache
        cache_settings (dict): cache settings, including:
            typed (bool): whether to enable type awareness
            ignore (set): parameter indices or keywords to ignore
            expire (int): cache expiry in seconds
        *args (P.args): positional arguments
        **kwargs (P.kwargs): keyword arguments

    Returns:
        T: the function return value

    """
    typed, ignore, expire = True, set(), None
    if cache_settings is not None:
        typed = cache_settings.get("typed", typed)
        ignore = cache_settings.get("ignore", ignore)
        expire = cache_settings.get("expire", expire)

    key = _buildcache_key(func, args, kwargs, typed, ignore)
    if (cached := cache.get(key)) is not None:
        return cached  # type: ignore[reportReturnType]

    result = func(*args, **kwargs)
    cache.set(key, result, expire=expire)
    return result


def cached_call_with_status[**P, T](
    func: Callable[P, T],
    cache_settings: dict | None = None,
    *args: P.args,
    **kwargs: P.kwargs,
) -> tuple[T, bool]:
    """High-performance cached call with parameter filtering and type awareness.

    Args:
        func (Callable): the function to cache
        cache_settings (dict): cache settings, including:
            typed (bool): whether to enable type awareness
            ignore (set): parameter indices or keywords to ignore
            expire (int): cache expiry in seconds
        *args (P.args): positional arguments
        **kwargs (P.kwargs): keyword arguments

    Returns:
        T: the function return value

    """
    typed, ignore, expire = True, set(), None
    if cache_settings is not None:
        typed = cache_settings.get("typed", typed)
        ignore = cache_settings.get("ignore", ignore)
        expire = cache_settings.get("expire", expire)

    key = _buildcache_key(func, args, kwargs, typed, ignore)
    if (cached := cache.get(key)) is not None:
        return cached, True  # type: ignore[reportReturnType]

    result = func(*args, **kwargs)
    cache.set(key, result, expire=expire)
    return result, False


async def async_cached_call_with_status[**P, T](
    func: Callable[P, Awaitable[T]],
    cache_settings: dict | None = None,
    *args: P.args,
    **kwargs: P.kwargs,
) -> tuple[T, bool]:
    """Like :func:`cached_call_with_status` for async functions.

    diskcache stays synchronous; lookups/sets are fast enough to run directly
    on the event loop.
    """
    typed, ignore, expire = True, set(), None
    if cache_settings is not None:
        typed = cache_settings.get("typed", typed)
        ignore = cache_settings.get("ignore", ignore)
        expire = cache_settings.get("expire", expire)

    key = _buildcache_key(func, args, kwargs, typed, ignore)
    if (cached := cache.get(key)) is not None:
        return cached, True  # type: ignore[reportReturnType]

    result = await func(*args, **kwargs)
    cache.set(key, result, expire=expire)
    return result, False


def _buildcache_key(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    typed: bool,
    ignore: set[int | str],
) -> tuple:
    """Build an efficient cache key structure."""
    # function identifier
    base = (f"{func.__module__}.{func.__qualname__}",)

    # filter positional arguments
    filtered_args = tuple(arg for idx, arg in enumerate(args) if idx not in ignore)

    # filter and sort keyword arguments
    sorted_kwargs = tuple(sorted((k, v) for k, v in kwargs.items() if k not in ignore))

    # combine the base key
    key = base + filtered_args + sorted_kwargs

    # add type information
    if typed:
        type_sig = (
            *(type(arg) for arg in filtered_args),
            *(type(v) for _, v in sorted_kwargs),
        )
        key += type_sig

    return key


def _atexit() -> None:
    cache["version"] = cache_version
    cache.expire()
    cache.close()


atexit.register(_atexit)
