"""Pydantic models for config.json — validation only; no I/O."""

from __future__ import annotations

import codecs
from typing import Annotated, Literal, Union

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
    usb_port_path: str | None = Field(
        default=None,
        description="Linux sysfs usb device name (e.g. 1-2.3) when disambiguating identical serials.",
    )
    default_label_size_id: str = Field(min_length=1)
    offset_x_mm: float = Field(default=0.0, ge=-100, le=100)
    offset_y_mm: float = Field(default=0.0, ge=-100, le=100)
    direction: Literal[0, 1] = Field(
        default=0,
        description="TSPL DIRECTION: 0 = default, 1 = 180° (only these values are supported).",
    )
    dpi: int = Field(default=203, ge=100, le=600)
    text_encoding: str = Field(
        default="utf-8",
        description=(
            "Python codec for TEXT payloads and raw print (e.g. utf-8, cp1252). "
            "PC865 in manuals maps to cp865."
        ),
    )

    @field_validator("text_encoding", mode="before")
    @classmethod
    def validate_text_encoding(cls, v: object) -> str:
        if v is None or (isinstance(v, str) and not v.strip()):
            return "utf-8"
        if not isinstance(v, str):
            return "utf-8"
        name = v.strip()
        try:
            codecs.lookup(name)
        except LookupError as e:
            raise ValueError(f"Unknown text encoding codec: {name!r}") from e
        return name

    @field_validator("usb_port_path", mode="before")
    @classmethod
    def strip_usb_port_path(cls, v: object) -> str | None:
        if v is None:
            return None
        if not isinstance(v, str):
            return None
        s = v.strip()
        return s if s else None

    @field_validator("direction", mode="before")
    @classmethod
    def direction_only_binary(cls, v: object) -> int:
        try:
            n = int(v)
        except (TypeError, ValueError):
            return 0
        return 1 if n == 1 else 0


# Template element legacy keys (x_mm, line_width_dots, etc.) and line_width_dots → mm migration.
_MM_PER_INCH = 25.4
_TEMPLATE_LEGACY_DPI = 203


def _normalize_template_element_dict(d: dict) -> dict:
    """Map old *_mm / line_width_dots keys; values are mm except legacy dots as noted."""
    m = dict(d)
    if "x" not in m and "x_mm" in m:
        m["x"] = m.pop("x_mm")
    if "y" not in m and "y_mm" in m:
        m["y"] = m.pop("y_mm")
    if m.get("type") == "box":
        if "width" not in m and "width_mm" in m:
            m["width"] = m.pop("width_mm")
        if "height" not in m and "height_mm" in m:
            m["height"] = m.pop("height_mm")
        if "line_width" not in m and "line_width_dots" in m:
            raw = m.pop("line_width_dots")
            try:
                dots = int(raw)
            except (TypeError, ValueError):
                dots = 2
            m["line_width"] = round(dots * _MM_PER_INCH / _TEMPLATE_LEGACY_DPI, 6)
    return m


class TemplateTextElement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["text"] = "text"
    x: float = Field(ge=-50, le=500)
    y: float = Field(ge=-50, le=500)
    font: str = Field(default="3", min_length=1, max_length=8)
    content: str = Field(min_length=1, max_length=4096)


class TemplateBoxElement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["box"] = "box"
    x: float = Field(ge=-50, le=500)
    y: float = Field(ge=-50, le=500)
    width: float = Field(gt=0, le=500)
    height: float = Field(gt=0, le=500)
    line_width: float = Field(default=0.25, gt=0, le=10)


TemplateElement = Annotated[
    Union[TemplateTextElement, TemplateBoxElement],
    Field(discriminator="type"),
]


class TemplateConfig(BaseModel):
    id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1)
    label_size_id: str = Field(min_length=1)
    elements: list[TemplateElement] = Field(default_factory=list)
    test_data: dict[str, str] = Field(
        default_factory=dict,
        description="Default placeholder values for /templates/…/test and the UI test dialog.",
    )

    @field_validator("elements", mode="before")
    @classmethod
    def default_text_type_for_legacy_elements(cls, v: object) -> object:
        if not isinstance(v, list):
            return []
        out: list[object] = []
        for item in v:
            if not isinstance(item, dict):
                out.append(item)
                continue
            m = dict(item)
            if m.get("type") is None:
                m["type"] = "text"
            out.append(_normalize_template_element_dict(m))
        return out

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
