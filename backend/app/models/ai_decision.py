from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.models.base import Base

class AIDecision(Base):
    __tablename__ = 'ai_decisions'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    symbol = Column(String(20), nullable=False)
    action = Column(String(10), nullable=False)  # BUY / SELL / HOLD
    quantity = Column(Integer, default=0)
    confidence = Column(Float, default=0.0)
    reasoning = Column(Text, default='')
    model = Column(String(100), default='')
    executed = Column(Integer, default=0)  # 0/1
    dry_run = Column(Integer, default=0)  # 0/1
    scheduled = Column(Integer, default=0)  # 0/1 (auto-trader)
    guardrail_note = Column(String(255), nullable=True)
    debate_transcript = Column(Text, nullable=True)
    was_correct = Column(Integer, nullable=True)  # 0/1
    outcome_pnl = Column(BigInteger, nullable=True)
    order_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship('User')