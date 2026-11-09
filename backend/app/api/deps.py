from typing import Generator, Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.models.user import User
from app.services.auth_service import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/api/auth/login', auto_error=False)

def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

DEFAULT_USER_EMAIL = 'local@simulator'

def _get_or_create_default_user(db: Session) -> User:
    from app.config import settings
    from app.models.account import Account
    from app.models.wallet import WalletTransaction
    user = db.query(User).filter(User.email == DEFAULT_USER_EMAIL).first()
    if user:
        return user
    user = User(name='Local User', email=DEFAULT_USER_EMAIL, password_hash='')
    db.add(user)
    db.flush()
    account = Account(
        user_id=user.id,
        cash_balance=settings.STARTING_CASH_PAISE,
        starting_balance=settings.STARTING_CASH_PAISE,
        realized_pnl_total=0
    )
    db.add(account)
    db.flush()
    db.add(WalletTransaction(
        user_id=user.id,
        type='INITIAL',
        amount=settings.STARTING_CASH_PAISE,
        balance_after=settings.STARTING_CASH_PAISE,
        note='Initial virtual wallet deposit'
    ))
    db.commit()
    db.refresh(user)
    return user

def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    # No-login mode: fall back to a single local user when not authenticated
    auth_token = token
    if not auth_token:
        auth_token = request.cookies.get('access_token')

    if auth_token:
        payload = decode_access_token(auth_token)
        if payload:
            user_id = payload.get('sub')
            if user_id:
                user = db.query(User).filter(User.id == int(user_id)).first()
                if user:
                    return user

    return _get_or_create_default_user(db)

def get_optional_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Optional[User]:
    try:
        return get_current_user(request, token, db)
    except HTTPException:
        return None
