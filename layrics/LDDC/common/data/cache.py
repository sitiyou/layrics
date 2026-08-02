# SPDX-FileCopyrightText: Copyright (C) 2024-2025 沉默の金 <cmzj@cmzj.org>
# SPDX-License-Identifier: GPL-3.0-only
"""Disk cache (slimmed from LDDC: cache dir moved to appdirs, no longer depends on common.paths)"""

import atexit
from collections.abc import Callable
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


def cached_call(
    func: Callable[P, T],
    cache_settings: dict | None = None,
    *args: P.args,
    **kwargs: P.kwargs,
) -> T:
    """高性能缓存调用函数,支持参数过滤和类型感知

    Args:
        func (Callable): 要缓存的函数
        cache_settings (dict): 缓存设置,包括:
            typed (bool): 是否启用类型感知
            ignore (set): 忽略的参数索引或关键字
            expire (int): 缓存过期时间,单位为秒
        *args (P.args): 位置参数
        **kwargs (P.kwargs): 关键字参数

    Returns:
        T: 函数返回值

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


def cached_call_with_status(
    func: Callable[P, T],
    cache_settings: dict | None = None,
    *args: P.args,
    **kwargs: P.kwargs,
) -> tuple[T, bool]:
    """高性能缓存调用函数,支持参数过滤和类型感知

    Args:
        func (Callable): 要缓存的函数
        cache_settings (dict): 缓存设置,包括:
            typed (bool): 是否启用类型感知
            ignore (set): 忽略的参数索引或关键字
            expire (int): 缓存过期时间,单位为秒
        *args (P.args): 位置参数
        **kwargs (P.kwargs): 关键字参数

    Returns:
        T: 函数返回值

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


def _buildcache_key(
    func: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    typed: bool,
    ignore: set[int | str],
) -> tuple:
    """构建高效缓存键结构"""
    # 函数标识
    base = (f"{func.__module__}.{func.__qualname__}",)

    # 过滤位置参数
    filtered_args = tuple(arg for idx, arg in enumerate(args) if idx not in ignore)

    # 过滤并排序关键字参数
    sorted_kwargs = tuple(sorted((k, v) for k, v in kwargs.items() if k not in ignore))

    # 组合基础键
    key = base + filtered_args + sorted_kwargs

    # 添加类型信息
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
