from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

class ChatRequest(BaseModel):
    """Request model untuk chat endpoint"""
    question: str = Field(..., min_length=1, max_length=500, description="User question")
    session_id: Optional[str] = Field(None, description="Session ID untuk conversation memory")
    
    class Config:
        json_schema_extra = {
            "example": {
                "question": "Jadwal kuliah kelas 1KA01",
                "session_id": "550e8400-e29b-41d4-a716-446655440000"
            }
        }

class ChatResponse(BaseModel):
    """Response model untuk chat endpoint"""
    answer: str = Field(..., description="Bot response")
    source: str = Field(..., description="Source of answer: database, llm_rag, clarification, error")
    intent: str = Field(..., description="Detected intent type")
    session_id: str = Field(..., description="Session ID")
    has_data: bool = Field(default=False, description="Whether response contains actual data")
    
    class Config:
        json_schema_extra = {
            "example": {
                "answer": "📅 **Jadwal Kuliah Kelas 1KA01**\n\n**Selasa:**\n• **Teknologi Kecerdasan Artifisial**\n  ⏰ -\n  🏢 UGTV\n  👨‍🏫 TEAM TEACHING",
                "source": "database",
                "intent": "jadwal_kuliah",
                "session_id": "550e8400-e29b-41d4-a716-446655440000",
                "has_data": True
            }
        }

class SessionClearRequest(BaseModel):
    """Request model untuk clear session"""
    session_id: str = Field(..., description="Session ID to clear")
    
    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "550e8400-e29b-41d4-a716-446655440000"
            }
        }

# Additional models untuk internal use atau future features

class ConversationExchange(BaseModel):
    """Model untuk conversation exchange"""
    timestamp: datetime
    user_message: str
    bot_response: str
    intent_type: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None

class SessionInfo(BaseModel):
    """Model untuk session information"""
    session_id: str
    created_at: datetime
    last_activity: datetime
    current_topic: Optional[str] = None
    pending_intent: Optional[str] = None
    exchanges_count: int = 0

class HealthCheckResponse(BaseModel):
    """Response model untuk health check"""
    status: str = Field(..., description="System status: healthy, unhealthy")
    timestamp: str = Field(..., description="Check timestamp")
    active_sessions: int = Field(..., description="Number of active sessions")
    pinecone_status: str = Field(..., description="Pinecone connection status")
    
class KnowledgeDocument(BaseModel):
    """Model untuk knowledge base document"""
    id: str
    content: str
    title: Optional[str] = None
    source: Optional[str] = None
    created_at: Optional[str] = None
    
class SearchResult(BaseModel):
    """Model untuk search results dari Pinecone"""
    content: str
    title: Optional[str] = None
    source: Optional[str] = None
    score: float = Field(..., ge=0.0, le=1.0)

# Error response models

class ErrorResponse(BaseModel):
    """Standard error response model"""
    error: bool = True
    message: str
    error_type: Optional[str] = None
    details: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "error": True,
                "message": "Kelas tidak ditemukan",
                "error_type": "kelas_not_found",
                "details": "Format kelas harus seperti: 1KA01, 2SI02"
            }
        }

# Stats and monitoring models

class SystemStats(BaseModel):
    """System statistics model"""
    active_sessions: int
    total_requests: Optional[int] = None
    uptime_seconds: Optional[float] = None
    memory_usage: Optional[Dict[str, Any]] = None
    pinecone_stats: Optional[Dict[str, Any]] = None

class DatabaseQueryResult(BaseModel):
    """Generic database query result"""
    success: bool
    data: List[Dict[str, Any]]
    count: int
    query_type: str
    parameters: Optional[Dict[str, Any]] = None