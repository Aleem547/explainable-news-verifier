"""Privacy-minimized verification activity statistics for the current user."""

from pydantic import BaseModel, Field


class DailyUsageStatistics(BaseModel):
    date: str
    total: int = Field(ge=0)
    successful: int = Field(ge=0)
    failed: int = Field(ge=0)
    rate_limited: int = Field(ge=0)


class UsageStatistics(BaseModel):
    window_days: int
    total_requests: int = Field(ge=0)
    successful_requests: int = Field(ge=0)
    failed_requests: int = Field(ge=0)
    rate_limited_requests: int = Field(ge=0)
    average_latency_ms: float = Field(ge=0)
    daily: list[DailyUsageStatistics]
