from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class MessageResponse(BaseModel):
    message: str


class HealthResponse(BaseModel):
    status: str
    app: str


class ApiErrorResponse(BaseModel):
    detail: str


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
