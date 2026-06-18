"""
RAG-Anything 统一业务异常类。

所有业务逻辑异常 SHALL 使用此处定义的异常类，
在 Router 层统一映射为 HTTPException 响应。
"""

from typing import Optional


class RAGAnythingError(Exception):
    """所有业务异常的基类。

    Args:
        message: 面向用户的错误描述
        detail: 面向开发者/日志的详细上下文（可选）
    """

    def __init__(self, message: str, detail: Optional[str] = None):
        self.message = message
        self.detail = detail or message
        super().__init__(message)


# ── 认证相关 ─────────────────────────────────────

class UnauthorizedError(RAGAnythingError):
    """认证失败（Token 无效、过期、用户不存在）"""


class ForbiddenError(RAGAnythingError):
    """权限不足（非管理员访问管理员资源）"""


class AccountLockedError(RAGAnythingError):
    """账号已被禁用"""


class AccountDisabledError(RAGAnythingError):
    """账号已被禁用"""


# ── 资源相关 ─────────────────────────────────────

class NotFoundError(RAGAnythingError):
    """请求的资源不存在（知识库、文档、智能体、工作流等）"""


class KnowledgeBaseNotFoundError(NotFoundError):
    """指定的知识库不存在"""


class DocumentNotFoundError(NotFoundError):
    """指定的文档不存在"""


class AgentNotFoundError(NotFoundError):
    """指定的智能体不存在"""


class WorkflowNotFoundError(NotFoundError):
    """指定的工作流不存在"""


# ── 业务逻辑相关 ─────────────────────────────────────

class ValidationError(RAGAnythingError):
    """输入验证失败（参数非法、格式错误、内容不安全）"""


class DocumentParseError(RAGAnythingError):
    """文档解析失败"""


class ProcessingError(RAGAnythingError):
    """后台处理失败"""


class RateLimitError(RAGAnythingError):
    """超出频率限制"""


class QueryTooLongError(ValidationError):
    """查询内容超过最大长度限制"""
