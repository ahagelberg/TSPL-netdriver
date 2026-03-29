"""JSON bodies for API (separate from persisted config models)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class TemplatePrintBody(BaseModel):
    template_id: str = Field(min_length=1)
    printer_id: str = Field(min_length=1)
    data: dict[str, str] = Field(default_factory=dict)

    @field_validator("data", mode="before")
    @classmethod
    def coerce_data_strings(cls, v: object) -> dict[str, str]:
        if not isinstance(v, dict):
            return {}
        return {str(k): str(val) for k, val in v.items()}


class RawPrintBody(BaseModel):
    printer_id: str = Field(min_length=1)
    tspl: str = Field(min_length=1)


class TemplateTestBody(BaseModel):
    printer_id: str = Field(min_length=1)
    data: dict[str, str] = Field(default_factory=dict)

    @field_validator("data", mode="before")
    @classmethod
    def coerce_test_body_strings(cls, v: object) -> dict[str, str]:
        if not isinstance(v, dict):
            return {}
        return {str(k): str(val) for k, val in v.items()}


class UsbDiscoverDevice(BaseModel):
    device_key: str
    label: str
    vendor_id: int
    product_id: int
    serial: str | None = None
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
