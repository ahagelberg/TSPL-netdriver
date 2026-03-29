"""Pydantic models for config.json — validation only; no I/O."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ServerConfig(BaseModel):
    bind_address: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8787, ge=1, le=65535)
    api_key: str = Field(min_length=8, description="Shared secret for /api/v1")
    cors_origins: list[str] = Field(
        default_factory=list,
        description=(
            "Allowed browser Origins for CORS (e.g. https://wp.example.com). "
            "The service expands http/https and www/apex for the same host:port (not for IPs). "
            "Empty = no CORS headers. Restart process after changing."
        ),
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def strip_cors_origins(cls, v: object) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        out: list[str] = []
        for item in v:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out


class LabelSize(BaseModel):
    id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1)
    width_mm: float = Field(gt=0, le=500)
    height_mm: float = Field(gt=0, le=500)
    gap_mm: float = Field(default=2.0, ge=0, le=50)


class PrinterConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1)
    vendor_id: int = Field(ge=0, le=0xFFFF)
    product_id: int = Field(ge=0, le=0xFFFF)
    serial: str | None = None
    default_label_size_id: str = Field(min_length=1)
    offset_x_mm: float = Field(default=0.0, ge=-100, le=100)
    offset_y_mm: float = Field(default=0.0, ge=-100, le=100)
    direction: Literal[0, 1] = Field(
        default=0,
        description="TSPL DIRECTION: 0 = default, 1 = 180° (only these values are supported).",
    )
    dpi: int = Field(default=203, ge=100, le=600)

    @field_validator("direction", mode="before")
    @classmethod
    def direction_only_binary(cls, v: object) -> int:
        try:
            n = int(v)
        except (TypeError, ValueError):
            return 0
        return 1 if n == 1 else 0


class TemplateElement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["text"] = "text"
    x_mm: float = Field(ge=-50, le=500)
    y_mm: float = Field(ge=-50, le=500)
    font: str = Field(default="3", min_length=1, max_length=8)
    content: str = Field(min_length=1, max_length=4096)


class TemplateConfig(BaseModel):
    id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1)
    label_size_id: str = Field(min_length=1)
    elements: list[TemplateElement] = Field(default_factory=list)
    test_data: dict[str, str] = Field(
        default_factory=dict,
        description="Default placeholder values for /templates/…/test and the UI test dialog.",
    )

    @field_validator("test_data", mode="before")
    @classmethod
    def stringify_test_data(cls, v: object) -> dict[str, str]:
        if not isinstance(v, dict):
            return {}
        return {str(k): str(val) for k, val in v.items()}


class AppConfig(BaseModel):
    server: ServerConfig
    label_sizes: list[LabelSize] = Field(default_factory=list)
    printers: list[PrinterConfig] = Field(default_factory=list)
    templates: list[TemplateConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids_and_references(self) -> AppConfig:
        ls_ids = [x.id for x in self.label_sizes]
        if len(ls_ids) != len(set(ls_ids)):
            raise ValueError("Duplicate label_sizes id")
        pr_ids = [x.id for x in self.printers]
        if len(pr_ids) != len(set(pr_ids)):
            raise ValueError("Duplicate printers id")
        tpl_ids = [x.id for x in self.templates]
        if len(tpl_ids) != len(set(tpl_ids)):
            raise ValueError("Duplicate templates id")
        all_ids = ls_ids + pr_ids + tpl_ids
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("ids must be unique across label_sizes, printers, and templates")
        ls_set = set(ls_ids)
        for p in self.printers:
            if p.default_label_size_id not in ls_set:
                raise ValueError(
                    f"Printer {p.id!r} default_label_size_id {p.default_label_size_id!r} not found"
                )
        for t in self.templates:
            if t.label_size_id not in ls_set:
                raise ValueError(
                    f"Template {t.id!r} label_size_id {t.label_size_id!r} not found"
                )
        return self
