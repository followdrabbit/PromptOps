from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel


class SettingSchema(BaseModel):
    key: str
    value: str


class ProviderSchema(BaseModel):
    id: Optional[int] = None
    name: str
    display_name: Optional[str] = None
    provider_type: Optional[str] = None
    website: Optional[str] = None
    region: Optional[str] = None
    compliance: Optional[str] = None
    tags: Optional[str] = None
    notes: Optional[str] = None


class EndpointSchema(BaseModel):
    id: Optional[int] = None
    name: str
    provider: str
    base_url: str
    endpoint_path: str
    model_name: str
    auth_type: str
    auth_header: Optional[str] = None
    auth_prefix: Optional[str] = None
    custom_headers: Optional[dict[str, Any]] = None
    default_params: Optional[dict[str, Any]] = None
    response_paths: Optional[str] = None
    response_type: Optional[str] = None
    timeout: Optional[int] = None
    retry_count: Optional[int] = None
    supports_tools: bool = False


class ChatSessionSchema(BaseModel):
    id: Optional[int] = None
    title: str
    endpoint_id: int
    created_at: Optional[datetime] = None


class ChatMessageSchema(BaseModel):
    id: Optional[int] = None
    session_id: int
    role: str
    content: str
    metadata: Optional[dict[str, Any]] = None
    created_at: Optional[datetime] = None


class TestSuiteSchema(BaseModel):
    id: Optional[int] = None
    name: str
    description: Optional[str] = None
    source_type: str
    source_path: Optional[str] = None
    default_endpoint_id: Optional[int] = None
    is_active: bool = True


class TestCaseSchema(BaseModel):
    id: Optional[int] = None
    suite_id: int
    order: Optional[int] = None
    enabled: bool = True
    test_name: str
    prompt: str
    expected_result: Optional[str] = None
    validation_type: Optional[str] = None
    tags: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    notes: Optional[str] = None


class TestRunSchema(BaseModel):
    id: Optional[int] = None
    suite_id: int
    endpoint_id: int
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    total_tests: Optional[int] = None
    passed: Optional[int] = None
    failed: Optional[int] = None
    errors: Optional[int] = None


class TestRunResultSchema(BaseModel):
    id: Optional[int] = None
    run_id: int
    test_id: int
    status: str
    prompt_sent: str
    response_received: Optional[str] = None
    latency_ms: Optional[int] = None
    error_message: Optional[str] = None
    timestamp: Optional[datetime] = None


class RedTeamSuiteSchema(BaseModel):
    id: Optional[int] = None
    name: str
    description: Optional[str] = None


class RedTeamCaseSchema(BaseModel):
    id: Optional[int] = None
    suite_id: int
    order: Optional[int] = None
    prompt: str
    purpose: Optional[str] = None
    expected_result: Optional[str] = None
    relevance: Optional[int] = None
    notes: Optional[str] = None


class RedTeamRunSchema(BaseModel):
    id: Optional[int] = None
    suite_id: int
    target_endpoint_id: int
    evaluator_endpoint_id: int
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    total_tests: Optional[int] = None
    passed: Optional[int] = None
    failed: Optional[int] = None
    errors: Optional[int] = None


class RedTeamRunResultSchema(BaseModel):
    id: Optional[int] = None
    run_id: int
    case_id: int
    status: str
    prompt_sent: str
    response_received: Optional[str] = None
    evaluation_summary: Optional[str] = None
    evaluation_score: Optional[float] = None
    evaluation_verdict: Optional[str] = None
    llm_judge_model: Optional[str] = None
    evaluation_verdict_justification: Optional[str] = None
    evaluation_score_justification: Optional[str] = None
    evaluator_response: Optional[str] = None
    latency_ms: Optional[int] = None
    evaluation_latency_ms: Optional[int] = None
    error_message: Optional[str] = None
    timestamp: Optional[datetime] = None


class AuditEventSchema(BaseModel):
    id: Optional[int] = None
    actor: str
    action: str
    entity_type: str
    entity_id: Optional[str] = None
    before_value: Optional[dict[str, Any]] = None
    after_value: Optional[dict[str, Any]] = None
    timestamp: Optional[datetime] = None
