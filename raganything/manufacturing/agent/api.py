"""
智能体 API 接口 — RESTful 端点、认证鉴权、速率限制。

端点:
- POST /agent/qa           文本问答
- POST /agent/video-locate  视频片段定位
- POST /agent/code-parse    代码解析
- POST /agent/fault-diagnosis 故障诊断
- POST /agent/fault-diagnosis/continue 继续诊断
- GET  /agent/health        健康检查
"""

import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# 速率限制存储 (简化实现，生产环境应用 Redis)
_rate_limit_store: dict[str, list[float]] = {}


class AgentAPI:
    """智能体 RESTful API 接口层。"""

    def __init__(self, qa_engine=None, video_locator=None,
                 code_parser=None, fault_diagnosis=None,
                 deployment_config=None,
                 rate_limit_per_minute: int = 30,
                 jwt_secret: str = "",
                 jwt_algorithm: str = "HS256"):
        """
        Args:
            qa_engine: QAEngine 实例
            video_locator: VideoLocator 实例
            code_parser: CodeParser 实例
            fault_diagnosis: FaultDiagnosisEngine 实例
            deployment_config: DeploymentConfig 实例
            rate_limit_per_minute: 默认速率限制
            jwt_secret: JWT 签名密钥 (生产环境必须设置)
            jwt_algorithm: JWT 签名算法，默认 HS256
        """
        self.qa_engine = qa_engine
        self.video_locator = video_locator
        self.code_parser = code_parser
        self.fault_diagnosis = fault_diagnosis
        self.deployment_config = deployment_config
        self.rate_limit_per_minute = rate_limit_per_minute
        self.jwt_secret = jwt_secret
        self.jwt_algorithm = jwt_algorithm

    # --- 认证 ---

    def authenticate(self, token: str) -> Optional[dict]:
        """验证 JWT Token 并返回用户信息。

        使用 PyJWT 进行签名验证。jwt_secret 未设置时拒绝所有请求。

        Returns:
            {"user_id", "institution_id", "role"} or None
        """
        if not token:
            return None
        if not self.jwt_secret:
            logger.error("JWT secret 未配置，拒绝认证请求")
            return None

        try:
            if token.startswith("Bearer "):
                token = token[7:]

            import jwt as pyjwt
            payload = pyjwt.decode(
                token,
                self.jwt_secret,
                algorithms=[self.jwt_algorithm],
                options={"require": ["exp", "sub"]},
            )
            return {
                "user_id": payload.get("sub", ""),
                "institution_id": payload.get("inst", "default"),
                "role": payload.get("role", "user"),
            }
        except pyjwt.ExpiredSignatureError:
            logger.warning("JWT Token 已过期")
            return None
        except pyjwt.InvalidTokenError as e:
            logger.warning(f"JWT 验证失败: {e}")
            return None

    # --- 速率限制 ---

    def check_rate_limit(self, institution_id: str) -> dict:
        """检查速率限制。

        Returns:
            {"allowed": bool, "remaining": int, "reset_in_seconds": int}
        """
        now = time.time()
        window = 60  # 1 分钟窗口
        cutoff = now - window

        # 清理过期记录
        if institution_id in _rate_limit_store:
            _rate_limit_store[institution_id] = [
                t for t in _rate_limit_store[institution_id] if t > cutoff
            ]
        else:
            _rate_limit_store[institution_id] = []

        # 获取该机构的速率限制
        limit = self.rate_limit_per_minute
        if self.deployment_config:
            cfg = self.deployment_config.get_config(institution_id)
            if cfg:
                limit = cfg.rate_limit_per_minute

        current = len(_rate_limit_store[institution_id])
        remaining = max(0, limit - current)
        allowed = remaining > 0

        if allowed:
            _rate_limit_store[institution_id].append(now)

        return {
            "allowed": allowed,
            "remaining": remaining,
            "reset_in_seconds": 60,
        }

    # --- 端点处理 ---

    def handle_qa(self, query: str, context: Optional[dict] = None,
                  institution_id: str = "") -> dict:
        """处理 POST /agent/qa 请求。"""
        if not self.qa_engine:
            return {"error": "QA 引擎未初始化", "status": 503}

        # 应用机构知识库范围
        if self.deployment_config and institution_id:
            scope = self.deployment_config.get_knowledge_scope(institution_id)
            if scope:
                context = context or {}
                context["knowledge_base_scope"] = scope

        response = self.qa_engine.answer(query, context)
        return self._response_to_dict(response)

    def handle_video_locate(self, query: str,
                            video_filter: Optional[str] = None,
                            top_k: int = 5) -> dict:
        """处理 POST /agent/video-locate 请求。"""
        if not self.video_locator:
            return {"error": "视频定位器未初始化", "status": 503}

        segments = self.video_locator.locate(query, video_filter, top_k)
        return {"query": query, "segments": segments, "total": len(segments)}

    def handle_code_parse(self, code: str,
                          language: str = "gcode") -> dict:
        """处理 POST /agent/code-parse 请求。"""
        if not self.code_parser:
            return {"error": "代码解析器未初始化", "status": 503}

        return self.code_parser.parse(code, language)

    def handle_fault_diagnosis(self, description: str,
                               session_id: str = "") -> dict:
        """处理 POST /agent/fault-diagnosis 请求。"""
        if not self.fault_diagnosis:
            return {"error": "故障诊断引擎未初始化", "status": 503}

        import uuid
        session_id = session_id or str(uuid.uuid4())[:8]
        return self.fault_diagnosis.start_diagnosis(session_id, description)

    def handle_diagnosis_continue(self, session_id: str,
                                  user_answer: str) -> dict:
        """处理 POST /agent/fault-diagnosis/continue 请求。"""
        if not self.fault_diagnosis:
            return {"error": "故障诊断引擎未初始化", "status": 503}

        return self.fault_diagnosis.continue_diagnosis(session_id, user_answer)

    def health_check(self) -> dict:
        """处理 GET /agent/health 请求。"""
        return {
            "status": "healthy",
            "services": {
                "qa_engine": self.qa_engine is not None,
                "video_locator": self.video_locator is not None,
                "code_parser": self.code_parser is not None,
                "fault_diagnosis": self.fault_diagnosis is not None,
            },
            "timestamp": time.time(),
        }

    # --- OpenAPI 文档 ---

    def get_openapi_spec(self, base_url: str = "/api/v1/manufacturing") -> dict:
        """生成 OpenAPI 3.1 规范文档。"""
        return {
            "openapi": "3.1.0",
            "info": {
                "title": "智能制造专业智能体 API",
                "version": "1.0.0",
                "description": "为天工讲堂平台及第三方系统提供智能制造领域智能问答、故障诊断等服务。",
            },
            "servers": [{"url": base_url}],
            "paths": {
                "/agent/qa": {
                    "post": {
                        "summary": "文本问答",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "query": {"type": "string", "description": "用户问题"},
                                            "context": {"type": "object", "description": "上下文限定"},
                                        },
                                        "required": ["query"],
                                    }
                                }
                            },
                        },
                        "responses": {
                            "200": {"description": "回答结果"},
                            "429": {"description": "请求频率超限"},
                        },
                    }
                },
                "/agent/video-locate": {
                    "post": {
                        "summary": "视频片段定位",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "query": {"type": "string"},
                                            "video_filter": {"type": "string"},
                                            "top_k": {"type": "integer", "default": 5},
                                        },
                                        "required": ["query"],
                                    }
                                }
                            },
                        },
                        "responses": {"200": {"description": "视频片段列表"}},
                    }
                },
                "/agent/code-parse": {
                    "post": {
                        "summary": "代码解析",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "code": {"type": "string"},
                                            "language": {"type": "string", "enum": ["gcode", "plc_instruction_list"]},
                                        },
                                        "required": ["code"],
                                    }
                                }
                            },
                        },
                        "responses": {"200": {"description": "解析结果"}},
                    }
                },
                "/agent/fault-diagnosis": {
                    "post": {
                        "summary": "故障诊断（开始新会话）",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "description": {"type": "string", "description": "故障现象描述"},
                                        },
                                        "required": ["description"],
                                    }
                                }
                            },
                        },
                        "responses": {"200": {"description": "诊断初判 + 追问"}},
                    }
                },
                "/agent/health": {
                    "get": {
                        "summary": "健康检查",
                        "responses": {"200": {"description": "服务状态"}},
                    }
                },
            },
        }

    # --- 私有方法 ---

    @staticmethod
    def _response_to_dict(response) -> dict:
        return {
            "query": response.query,
            "answer": response.answer,
            "citations": response.citations,
            "confidence": response.confidence,
            "processing_time_ms": response.processing_time_ms,
            "needs_human_review": response.needs_human_review,
        }

