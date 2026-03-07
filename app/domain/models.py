from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


class Provider(Base):
    __tablename__ = "providers"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True, nullable=False)
    display_name = Column(String(160), nullable=True)
    provider_type = Column(String(80), nullable=True)
    website = Column(String(255), nullable=True)
    region = Column(String(120), nullable=True)
    compliance = Column(String(200), nullable=True)
    tags = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Setting(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(String(500), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Endpoint(Base):
    __tablename__ = "endpoints"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    provider = Column(String(60), nullable=False)
    base_url = Column(String(255), nullable=False)
    endpoint_path = Column(String(255), nullable=False)
    model_name = Column(String(120), nullable=False)
    auth_type = Column(String(30), nullable=False)
    auth_header = Column(String(120), nullable=True)
    auth_prefix = Column(String(40), nullable=True)
    custom_headers = Column(JSON, nullable=True)
    default_params = Column(JSON, nullable=True)
    response_paths = Column(Text, nullable=True)
    response_type = Column(String(30), nullable=True)
    timeout = Column(Integer, nullable=True)
    retry_count = Column(Integer, nullable=True)
    supports_tools = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    secret = relationship("EndpointSecret", back_populates="endpoint", uselist=False, cascade="all, delete-orphan")
    test_suites = relationship("TestSuite", back_populates="default_endpoint")
    chat_sessions = relationship("ChatSession", back_populates="endpoint")


class EndpointSecret(Base):
    __tablename__ = "endpoint_secrets"

    id = Column(Integer, primary_key=True)
    endpoint_id = Column(Integer, ForeignKey("endpoints.id"), nullable=False, unique=True)
    encrypted_secret = Column(Text, nullable=False)
    secret_type = Column(String(40), nullable=False)
    last_rotated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    endpoint = relationship("Endpoint", back_populates="secret")


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    endpoint_id = Column(Integer, ForeignKey("endpoints.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    endpoint = relationship("Endpoint", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    meta = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session = relationship("ChatSession", back_populates="messages")


class TestSuite(Base):
    __tablename__ = "test_suites"

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    source_type = Column(String(20), nullable=False)
    source_path = Column(String(255), nullable=True)
    default_endpoint_id = Column(Integer, ForeignKey("endpoints.id"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    test_cases = relationship("TestCase", back_populates="suite", cascade="all, delete-orphan")
    default_endpoint = relationship("Endpoint", back_populates="test_suites")


class TestCase(Base):
    __tablename__ = "test_cases"

    id = Column(Integer, primary_key=True)
    suite_id = Column(Integer, ForeignKey("test_suites.id"), nullable=False)
    order = Column(Integer, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    test_name = Column(String(200), nullable=False)
    prompt = Column(Text, nullable=False)
    expected_result = Column(Text, nullable=True)
    validation_type = Column(String(40), nullable=True)
    tags = Column(String(200), nullable=True)
    temperature = Column(Float, nullable=True)
    max_tokens = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    suite = relationship("TestSuite", back_populates="test_cases")


class TestRun(Base):
    __tablename__ = "test_runs"

    id = Column(Integer, primary_key=True)
    suite_id = Column(Integer, ForeignKey("test_suites.id"), nullable=False)
    endpoint_id = Column(Integer, ForeignKey("endpoints.id"), nullable=False)
    status = Column(String(40), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    total_tests = Column(Integer, nullable=True)
    passed = Column(Integer, nullable=True)
    failed = Column(Integer, nullable=True)
    errors = Column(Integer, nullable=True)


class TestRunResult(Base):
    __tablename__ = "test_run_results"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("test_runs.id"), nullable=False)
    test_id = Column(Integer, ForeignKey("test_cases.id"), nullable=False)
    status = Column(String(40), nullable=False)
    prompt_sent = Column(Text, nullable=False)
    response_received = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True)
    actor = Column(String(120), nullable=False)
    action = Column(String(120), nullable=False)
    entity_type = Column(String(120), nullable=False)
    entity_id = Column(String(120), nullable=True)
    before_value = Column(JSON, nullable=True)
    after_value = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
