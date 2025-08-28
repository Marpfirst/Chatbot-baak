# Logika untuk mengelola memori percakapan per sesi
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import uuid
from dataclasses import dataclass, asdict
from app.config import settings

@dataclass
class ConversationExchange:
    timestamp: datetime
    user_message: str
    bot_response: str
    intent_type: Optional[str] = None
    parameters: Optional[Dict] = None

@dataclass
class SessionContext:
    session_id: str
    created_at: datetime
    last_activity: datetime
    current_topic: Optional[str] = None
    pending_intent: Optional[str] = None  # For clarification flow
    pending_parameters: Optional[Dict] = None
    exchanges: List[ConversationExchange] = None
    
    def __post_init__(self):
        if self.exchanges is None:
            self.exchanges = []

class MemoryManager:
    def __init__(self):
        self.sessions: Dict[str, SessionContext] = {}
        self.timeout_minutes = settings.SESSION_TIMEOUT_MINUTES
        self.max_exchanges = settings.MAX_MEMORY_EXCHANGES
    
    def create_session(self) -> str:
        """Create new session and return session ID"""
        session_id = str(uuid.uuid4())
        now = datetime.now()
        
        self.sessions[session_id] = SessionContext(
            session_id=session_id,
            created_at=now,
            last_activity=now,
            exchanges=[]
        )
        
        return session_id
    
    def get_session(self, session_id: str) -> Optional[SessionContext]:
        """Get session by ID, check if still active"""
        if session_id not in self.sessions:
            return None
        
        session = self.sessions[session_id]
        
        # Check if session expired
        timeout_threshold = datetime.now() - timedelta(minutes=self.timeout_minutes)
        if session.last_activity < timeout_threshold:
            self.cleanup_session(session_id)
            return None
        
        return session
    
    def update_session_activity(self, session_id: str) -> bool:
        """Update last activity timestamp"""
        session = self.get_session(session_id)
        if session:
            session.last_activity = datetime.now()
            return True
        return False
    
    def add_exchange(self, session_id: str, user_message: str, bot_response: str, 
                    intent_type: Optional[str] = None, parameters: Optional[Dict] = None):
        """Add conversation exchange to session memory"""
        session = self.get_session(session_id)
        if not session:
            return False
        
        exchange = ConversationExchange(
            timestamp=datetime.now(),
            user_message=user_message,
            bot_response=bot_response,
            intent_type=intent_type,
            parameters=parameters
        )
        
        session.exchanges.append(exchange)
        
        # Keep only recent exchanges
        if len(session.exchanges) > self.max_exchanges:
            session.exchanges = session.exchanges[-self.max_exchanges:]
        
        self.update_session_activity(session_id)
        return True
    
    def set_pending_clarification(self, session_id: str, intent: str, parameters: Dict = None):
        """Set pending intent for clarification flow"""
        session = self.get_session(session_id)
        if session:
            session.pending_intent = intent
            session.pending_parameters = parameters or {}
            self.update_session_activity(session_id)
    
    def get_pending_clarification(self, session_id: str) -> Optional[tuple]:
        """Get pending clarification data"""
        session = self.get_session(session_id)
        if session and session.pending_intent:
            return session.pending_intent, session.pending_parameters
        return None
    
    def clear_pending_clarification(self, session_id: str):
        """Clear pending clarification"""
        session = self.get_session(session_id)
        if session:
            session.pending_intent = None
            session.pending_parameters = None
            self.update_session_activity(session_id)
    
    def get_conversation_context(self, session_id: str) -> List[Dict]:
        """Get recent conversation context for LLM"""
        session = self.get_session(session_id)
        if not session:
            return []
        
        context = []
        for exchange in session.exchanges:
            context.extend([
                {"role": "user", "content": exchange.user_message},
                {"role": "assistant", "content": exchange.bot_response}
            ])
        
        return context
    
    def cleanup_session(self, session_id: str):
        """Remove session from memory"""
        if session_id in self.sessions:
            del self.sessions[session_id]
    
    def cleanup_expired_sessions(self):
        """Clean up all expired sessions"""
        now = datetime.now()
        timeout_threshold = now - timedelta(minutes=self.timeout_minutes)
        
        expired_sessions = [
            sid for sid, session in self.sessions.items()
            if session.last_activity < timeout_threshold
        ]
        
        for sid in expired_sessions:
            self.cleanup_session(sid)
        
        return len(expired_sessions)
    
    def get_session_stats(self) -> Dict:
        """Get memory statistics"""
        now = datetime.now()
        active_sessions = len(self.sessions)
        
        return {
            "active_sessions": active_sessions,
            "timestamp": now.isoformat()
        }

# Singleton instance
memory_manager = MemoryManager()