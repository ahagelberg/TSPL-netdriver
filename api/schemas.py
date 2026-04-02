"""JSON bodies for API (separate from persisted config models)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from config.models import TemplateElement, coerce_legacy_label_size_mm_keys


def _coerce_string_dict(v: object) -> dict[str, str]:
    if not isinstance(v, dict):
        return {}
    return {str(k): str(val) for k, val in v.items()}


class TemplatePrintBody(BaseModel):
    template_id: str = Field(min_length=1)
    printer_id: str = Field(min_length=1)
    data: dict[str, str] = Field(default_factory=dict)

    @field_validator("data", mode="before")
    @classmethod
    def coerce_data_strings(cls, v: object) -> dict[str, str]:
        return _coerce_string_dict(v)


class RawPrintBody(BaseModel):
    printer_id: str = Field(min_length=1)
    tspl: str = Field(min_length=1)


class InlineLabelSizeBody(BaseModel):
    """Inline label dimensions; millimetres (field names omit unit suffix)."""

    width: float = Field(gt=0, le=500)
    height: float = Field(gt=0, le=500)
    gap: float = Field(default=2.0, ge=0, le=50)

    @model_validator(mode="before")
    @classmethod
    def _legacy_mm_keys(cls, data: object) -> object:
        return coerce_legacy_label_size_mm_keys(data)


class LabelPrintBody(BaseModel):
    printer_id: str = Field(min_length=1)
    label_size: InlineLabelSizeBody
    elements: list[TemplateElement] = Field(default_factory=list)
    data: dict[str, str] = Field(default_factory=dict)

    @field_validator("data", mode="before")
    @classmethod
    def coerce_label_data_strings(cls, v: object) -> dict[str, str]:
        return _coerce_string_dict(v)


class TemplateTestBody(BaseModel):
    printer_id: str = Field(min_length=1)
    data: dict[str, str] = Field(default_factory=dict)

    @field_validator("data", mode="before")
    @classmethod
    def coerce_test_body_strings(cls, v: object) -> dict[str, str]:
        return _coerce_string_dict(v)


class TemplatePreviewBody(BaseModel):
    """PNG preview from in-memory elements (matches unsaved template editor)."""

    printer_id: str = Field(min_length=1)
    label_size_id: str = Field(min_length=1)
    elements: list[TemplateElement] = Field(default_factory=list)
    test_data: dict[str, str] = Field(default_factory=dict)
    data: dict[str, str] = Field(default_factory=dict)

    @field_validator("test_data", "data", mode="before")
    @classmethod
    def coerce_preview_strings(cls, v: object) -> dict[str, str]:
        return _coerce_string_dict(v)


class UsbDiscoverDevice(BaseModel):
    device_key: str
    label: str
    vendor_id: int
    product_id: int
    serial: str | None = None
    usb_port_path: str
    manufacturer: str | None = None
    product: str | None = None


class UsbDiscoverData(BaseModel):
    devices: list[UsbDiscoverDevice]
    usb_total: int
    tspl_like_count: int


class OkEnvelope(BaseModel):
    ok: bool = True
    data: dict | list | None = None


class ErrEnvelope(BaseModel):
    ok: bool = False
    error: dict[str, Any]
