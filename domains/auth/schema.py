from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    username: str | None = None
    email: str | None = None
    phone: str | None = None
    whatsapp_id: str | None = Field(default=None, alias="whatsappId")
    wechat_id: str | None = Field(default=None, alias="wechatId")
    password: str

    @property
    def principal(self) -> str:
        return (
            self.username or self.email or self.phone or self.whatsapp_id or self.wechat_id or ""
        ).strip()


class LoginUser(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    username: str
    display_name: str
    role: str
    scopes: list[str]
    stage: str | None = None
    customer_id: str | None = Field(default=None, alias="customerId")
    stage_label: str | None = Field(default=None, alias="stageLabel")
    canonical_role: str = Field(default="operator", alias="canonicalRole")
    home_path: str = Field(default="/platform", alias="homePath")
    shell: str = "platform"
    can_create_orders: bool = Field(default=False, alias="canCreateOrders")


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token: str | None = None
    token_type: str = "bearer"
    expires_in: int
    user: LoginUser
