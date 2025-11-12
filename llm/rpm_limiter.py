"""
RPM (Requests Per Minute) Limiter
使用滑动窗口算法实现 LLM API 调用频率限制
"""

import time
import threading
from typing import List, Optional


class RPMLimiter:
    """
    基于滑动窗口的 RPM 限流器

    特性:
    - 线程安全（使用 threading.Lock）
    - 自动等待（超限时阻塞而非报错）
    - 滑动窗口算法（精确控制每分钟请求数）

    Example:
        limiter = RPMLimiter(rpm_limit=60)
        limiter.acquire()  # 获取一个请求配额，超限时自动等待
    """

    def __init__(self, rpm_limit: int):
        """
        初始化 RPM 限流器

        Args:
            rpm_limit: 每分钟允许的最大请求数
        """
        if rpm_limit <= 0:
            raise ValueError(f"rpm_limit must be positive, got {rpm_limit}")

        self.rpm_limit = rpm_limit
        self.request_times: List[float] = []  # 请求时间戳队列
        self.lock = threading.Lock()  # 线程锁

    def acquire(self) -> None:
        """
        获取一个请求配额

        如果当前分钟内已达到限制，会自动等待直到可以发起请求
        此方法是线程安全的
        """
        with self.lock:
            now = time.time()

            # 清理 60 秒之前的记录（滑动窗口）
            cutoff = now - 60.0
            self.request_times = [t for t in self.request_times if t > cutoff]

            # 检查是否超限
            if len(self.request_times) >= self.rpm_limit:
                # 计算需要等待的时间
                # 最早的请求需要在 60 秒后过期
                oldest = self.request_times[0]
                wait_time = 60.0 - (now - oldest) + 0.1  # +0.1s buffer

                if wait_time > 0:
                    print(f"⏱ RPM limit reached ({self.rpm_limit} req/min). Waiting {wait_time:.1f}s...")

                    # 释放锁期间等待（允许其他线程执行）
                    self.lock.release()
                    try:
                        time.sleep(wait_time)
                    finally:
                        self.lock.acquire()

                    # 重新获取当前时间并清理过期记录
                    now = time.time()
                    cutoff = now - 60.0
                    self.request_times = [t for t in self.request_times if t > cutoff]

            # 记录本次请求时间
            self.request_times.append(now)

    def get_current_usage(self) -> dict:
        """
        获取当前限流器的使用情况（用于调试/监控）

        Returns:
            dict: 包含当前使用情况的字典
                - limit: RPM 限制
                - current: 当前分钟内的请求数
                - available: 剩余可用请求数
        """
        with self.lock:
            now = time.time()
            cutoff = now - 60.0
            active_requests = [t for t in self.request_times if t > cutoff]

            return {
                "limit": self.rpm_limit,
                "current": len(active_requests),
                "available": max(0, self.rpm_limit - len(active_requests))
            }


class GlobalRPMLimiter:
    """
    全局 RPM 限流器管理器

    为每个 base_url 维护独立的限流器实例
    支持多个不同的 API 服务
    """

    _limiters: dict[str, RPMLimiter] = {}
    _lock = threading.Lock()

    @classmethod
    def get_limiter(cls, key: str, rpm_limit: int) -> Optional[RPMLimiter]:
        """
        获取或创建指定 key 的限流器

        Args:
            key: 限流器的唯一标识（通常是 base_url）
            rpm_limit: RPM 限制值，如果为 None 或 0 则不限流

        Returns:
            RPMLimiter 实例，如果 rpm_limit <= 0 则返回 None
        """
        if rpm_limit is None or rpm_limit <= 0:
            return None

        with cls._lock:
            if key not in cls._limiters:
                cls._limiters[key] = RPMLimiter(rpm_limit)
            else:
                # 如果已存在但限制值不同，更新限制值
                existing = cls._limiters[key]
                if existing.rpm_limit != rpm_limit:
                    print(f"⚠ Updating RPM limit for '{key}': {existing.rpm_limit} -> {rpm_limit}")
                    cls._limiters[key] = RPMLimiter(rpm_limit)

            return cls._limiters[key]

    @classmethod
    def clear_all(cls):
        """清除所有限流器（主要用于测试）"""
        with cls._lock:
            cls._limiters.clear()
