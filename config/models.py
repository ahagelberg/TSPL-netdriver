"""Pydantic models for config.json — validation only; no I/O."""

from __future__ import annotations

import codecs
import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

_PLACEHOLDER_KEY_RE = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")


def coerce_legacy_label_size_mm_keys(data: Any) -> Any:
    """Map legacy *_mm keys to canonical names when loading JSON (config/API)."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    if "width_mm" in out:
        if "width" not in out:
            out["width"] = out["width_mm"]
        out.pop("width_mm", None)
    if "height_mm" in out:
        if "height" not in out:
            out["height"] = out["height_mm"]
        out.pop("height_mm", None)
    if "gap_mm" in out:
        if "gap" not in out:
            out["gap"] = out["gap_mm"]
        out.pop("gap_mm", None)
    return out


def coerce_legacy_printer_offset_mm_keys(data: Any) -> Any:
    """Map legacy offset_*_mm keys to offset_* when loading JSON."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    if "offset_x_mm" in out:
        if "offset_x" not in out:
            out["offset_x"] = out["offset_x_mm"]
        out.pop("offset_x_mm", None)
    if "offset_y_mm" in out:
        if "offset_y" not in out:
            out["offset_y"] = out["offset_y_mm"]
        out.pop("offset_y_mm", None)
    return out


def collect_placeholder_keys_from_elements(elements: list[Any]) -> list[str]:
    keys: set[str] = set()
    for el in elements:
        if el.type == "text":
            keys.update(_PLACEHOLDER_KEY_RE.findall(el.content))
    return sorted(keys)


class ServerConfig(BaseModel):
    bind_address: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8787, ge=1, le=65535)
    api_key: str = Field(min_length=8, description="Shared secret for /api/v1")
    font_cache_dir: str = Field(
        default=".tspl-font-cache",
        min_length=1,
        description="Directory used to cache downloaded web fonts.",
    )
    font_fetch_timeout_seconds: float = Field(
        default=5.0,
        gt=0.0,
        le=120.0,
        description="Timeout for fetching web fonts over HTTP/HTTPS.",
    )
    font_local_roots: list[str] = Field(
        default_factory=list,
        description="Optional allowed local font root directories. Empty means any readable local path.",
    )
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

    @field_validator("font_local_roots", mode="before")
    @classmethod
    def strip_font_local_roots(cls, v: object) -> list[str]:
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
    """Label stock dimensions; values are millimetres (field names omit unit suffix)."""

    id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1)
    width: float = Field(gt=0, le=500)
    height: float = Field(gt=0, le=500)
    gap: float = Field(default=2.0, ge=0, le=50)

    @model_validator(mode="before")
    @classmethod
    def _legacy_mm_keys(cls, data: Any) -> Any:
        return coerce_legacy_label_size_mm_keys(data)


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
    offset_x: float = Field(default=0.0, ge=-100, le=100)
    offset_y: float = Field(default=0.0, ge=-100, le=100)
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

    @model_validator(mode="before")
    @classmethod
    def _legacy_offset_mm_keys(cls, data: Any) -> Any:
        return coerce_legacy_printer_offset_mm_keys(data)


class TemplateTextElement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["text"] = "text"
    x: float = Field(ge=-50, le=500)
    y: float = Field(ge=-50, le=500)
    font: str = Field(default="3", min_length=1, max_length=4096)
    size: float = Field(default=3.0, gt=0, le=50)
    font_weight: int = Field(
        default=400,
        ge=100,
        le=900,
        description="CSS font weight (100–900); snapped to nearest 100. Used for raster fonts and named families.",
    )
    font_style: Literal["normal", "italic"] = Field(
        default="normal",
        description="Used for raster fonts and named families (fontconfig + Google Fonts).",
    )
    content: str = Field(min_length=1, max_length=4096)

    @field_validator("font_weight", mode="before")
    @classmethod
    def snap_font_weight(cls, v: object) -> int:
        if v is None or v == "":
            return 400
        try:
            n = int(v)
        except (TypeError, ValueError):
            return 400
        n = int(round(n / 100)) * 100
        return max(100, min(900, n))

    @field_validator("font_style", mode="before")
    @classmethod
    def normalize_font_style(cls, v: object) -> str:
        if v is None or v == "":
            return "normal"
        s = str(v).strip().lower()
        if s in ("normal", "italic"):
            return s
        raise ValueError("font_style must be 'normal' or 'italic'")


class TemplateBoxElement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["box"] = "box"
    x: float = Field(ge=-50, le=500)
    y: float = Field(ge=-50, le=500)
    width: float = Field(gt=0, le=500)
    height: float = Field(gt=0, le=500)
    line_width: float = Field(default=0.25, gt=0, le=10)


class TemplateCircleElement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["circle"] = "circle"
    x: float = Field(ge=-50, le=500)
    y: float = Field(ge=-50, le=500)
    diameter: float = Field(gt=0, le=500)
    line_width: float = Field(default=0.3, gt=0, le=10)


class TemplateBitmapElement(BaseModel):
    """Embedded mono bitmap: position in mm; payload is printer-ready TSPL BITMAP bytes (base64)."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["bitmap"] = "bitmap"
    x: float = Field(ge=-50, le=500)
    y: float = Field(ge=-50, le=500)
    width: int = Field(gt=0, le=20000, description="Bitmap width in dots (bytes per row derived when packing)")
    height: int = Field(gt=0, le=20000, description="Bitmap height in dots")
    data: str = Field(min_length=1, description="Base64-encoded TSPL BITMAP payload (row-major)")


TemplateElement = Annotated[
    Union[
        TemplateTextElement,
        TemplateBoxElement,
        TemplateCircleElement,
        TemplateBitmapElement,
    ],
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
    def elements_must_be_list(cls, v: object) -> object:
        if not isinstance(v, list):
            return []
        return v

    @field_validator("test_data", mode="before")
    @classmethod
    def stringify_test_data(cls, v: object) -> dict[str, str]:
        if not isinstance(v, dict):
            return {}
        return {str(k): str(val) for k, val in v.items()}

    @computed_field
    @property
    def placeholder_keys(self) -> list[str]:
        return collect_placeholder_keys_from_elements(list(self.elements))


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
