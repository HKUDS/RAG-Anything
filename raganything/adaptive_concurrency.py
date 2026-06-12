"""
LLM 自适应并发 — 滑动窗口错误率检测 + 动态并发升降级。

用法:
    from raganything.utils.adaptive_concurrency import AdaptiveConcurrency

    ac = AdaptiveConcurrency(initial=8, min_concurrency=1)
    ac.record_success()   # 记录成功
    ac.record_error()     # 记录失败
    workers = ac.current  # 获取当前并发数
"""

import collections
import logging
import os

logger = logging.getLogger(__name__)


class AdaptiveConcurrency:
    """基于滑动窗口错误率的自适应并发控制。

    错误率超过阈值时自动减半并发，连续成功后恢复。
    """

    def __init__(self, initial: int = 8, min_concurrency: int = 1,
                 max_concurrency: int = 16,
                 window_size: int = 10,
                 error_threshold: float = 0.3,
                 recovery_streak: int = 20):
        """
        Args:
            initial: 初始并发数
            min_concurrency: 最小并发数
            max_concurrency: 最大并发数
            window_size: 滑动窗口大小
            error_threshold: 触发降级的错误率阈值
            recovery_streak: 自动恢复所需的连续成功次数
        """
        self.initial = initial
        self.min = min_concurrency
        self.max = max_concurrency
        self._current = initial
        self._window: collections.deque[bool] = collections.deque(maxlen=window_size)
        self._streak = 0  # 连续成功计数
        self._recovery_streak = recovery_streak
        self._error_threshold = error_threshold
        self._downgraded = False

    @property
    def current(self) -> int:
        return self._current

    def record_success(self) -> None:
        """记录一次成功调用。"""
        self._window.append(True)
        self._streak += 1

        if self._downgraded and self._streak >= self._recovery_streak:
            self._current = min(self._current * 2, self.initial, self.max)
            self._downgraded = False
            self._streak = 0
            logger.info(f"Adaptive concurrency recovered to {self._current}")

    def record_error(self) -> None:
        """记录一次失败调用。"""
        self._window.append(False)
        self._streak = 0

        if not self._window:
            return

        error_rate = sum(1 for ok in self._window if not ok) / len(self._window)

        if error_rate >= self._error_threshold and self._current > self.min:
            self._current = max(self._current // 2, self.min)
            self._downgraded = True
            self._streak = 0
            logger.warning(
                f"Adaptive concurrency downgraded to {self._current} "
                f"(error rate: {error_rate:.0%})"
            )

    def get_stats(self) -> dict:
        """获取当前状态统计。"""
        errors = sum(1 for ok in self._window if not ok)
        total = len(self._window)
        return {
            "current_concurrency": self._current,
            "initial_concurrency": self.initial,
            "error_rate": round(errors / total, 2) if total > 0 else 0,
            "downgraded": self._downgraded,
            "success_streak": self._streak,
        }


# 全局实例（按用途区分）
_instances: dict[str, AdaptiveConcurrency] = {}

def get_adaptive_concurrency(name: str = "default", initial: int = 8) -> AdaptiveConcurrency:
    """获取或创建自适应并发实例。

    Args:
        name: 实例名称（llm/embedding/multimodal）
        initial: 初始并发数
    """
    if name not in _instances:
        enabled = os.getenv("ADAPTIVE_CONCURRENCY_ENABLED", "true").lower() == "true"
        if enabled:
            error_rate = float(os.getenv("ADAPTIVE_CONCURRENCY_ERROR_RATE", "0.3"))
            _instances[name] = AdaptiveConcurrency(
                initial=initial, error_threshold=error_rate,
            )
        else:
            # 禁用时返回普通对象，current 始终返回 initial
            _instances[name] = AdaptiveConcurrency(
                initial=initial, min_concurrency=initial,
                error_threshold=1.0,
            )
    return _instances[name]
