"""AI 只提供标题识别或候选选择，不产生刮削元数据。"""

import re
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictInt,
    field_validator,
    model_validator,
)


class AIConfig(BaseModel):
    """DeepSeek 辅助配置；默认禁用，地址和模型不可任意替换。"""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    model: Literal["deepseek-flash"] = "deepseek-flash"
    timeout_seconds: int = Field(default=15, ge=1, le=45)
    confidence_threshold: float = Field(default=0.9, ge=0.8, le=1)


class AIConfigRequest(AIConfig):
    """空密钥保留现有密钥，删除必须使用独立接口。"""

    api_key: SecretStr | None = Field(default=None, max_length=4096)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and any(ord(char) < 32 for char in value.get_secret_value()):
            raise ValueError("invalid API Key")
        return value


class AIConfigResponse(AIConfig):
    """永远不含明文或加密后的密钥。"""

    has_api_key: bool = False


class AISuggestion(BaseModel):
    """经过本地复验的有限建议，禁止季集和 NFO 等额外字段。"""

    model_config = ConfigDict(extra="forbid")

    action: Literal["identify_title", "select_candidate"]
    title: str | None = Field(default=None, max_length=160, strict=True)
    selected_id: StrictInt | None = None
    confidence: float = Field(ge=0, le=1, strict=True)
    reason: str = Field(default="", max_length=240, strict=True)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        # 拒绝多行、路径和 URL，不允许建议越过「搜索词」的信任边界。
        if not value.strip() or any(
            ord(char) < 32 or 127 <= ord(char) <= 159 or char in "\u2028\u2029" for char in value
        ):
            raise ValueError("invalid title")
        if "/" in value or "\\" in value or re.search(r"(?:\w+://|www\.)", value, re.I):
            raise ValueError("invalid title")
        return value.strip()

    @model_validator(mode="after")
    def validate_action_fields(self) -> "AISuggestion":
        if self.action == "identify_title":
            if self.title is None or self.selected_id is not None:
                raise ValueError("identify_title requires only title")
        elif self.selected_id is None or self.title is not None:
            raise ValueError("select_candidate requires only selected_id")
        return self
