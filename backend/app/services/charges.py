"""Indian market charges (taxes + fees) for a single executed leg.

All amounts in paise. Rates are indicative of NSE cash segment for
discount brokerages (Zerodha/Groww style). Adjust in this module if needed.

Breakdown (per executed order/leg):
  - Brokerage: flat fee from settings.FLAT_FEE_PAISE (default 0)
  - STT: 0.1% on sell (CNC delivery), 0.025% on sell (MIS intraday equity)
  - Transaction charges (NSE): 0.00297% on turnover (both sides)
  - SEBI turnover fee: 0.0001% on turnover (both sides)
  - Stamp duty: 0.015% on buy (CNC), 0.003% on buy (MIS)
  - GST: 18% on (brokerage + transaction charges + SEBI)
"""
from app.config import settings


def _pct(paise_amount: int, pct: float) -> int:
    # pct is a percent value, e.g. 0.1 means 0.1%
    return int(round(paise_amount * pct / 100.0))


def compute_charges(side: str, product_type: str, quantity: int, price_paise: int) -> int:
    side = (side or '').upper()
    product_type = (product_type or '').upper()
    turnover = quantity * price_paise  # paise

    brokerage = int(settings.FLAT_FEE_PAISE or 0)

    # STT (Securities Transaction Tax) - on sell side only for equity
    if side == 'SELL':
        if product_type == 'MIS':
            stt = _pct(turnover, 0.025)
        else:
            stt = _pct(turnover, 0.1)
    else:
        stt = 0

    # NSE transaction charges (both sides)
    txn = _pct(turnover, 0.00297)

    # SEBI turnover fee (both sides)
    sebi = _pct(turnover, 0.0001)

    # Stamp duty - on buy side only
    if side == 'BUY':
        if product_type == 'MIS':
            stamp = _pct(turnover, 0.003)
        else:
            stamp = _pct(turnover, 0.015)
    else:
        stamp = 0

    # GST 18% on (brokerage + txn + sebi)
    gst = int(round((brokerage + txn + sebi) * 0.18))

    total = brokerage + stt + txn + sebi + stamp + gst
    return max(0, total)


def charges_breakdown(side: str, product_type: str, quantity: int, price_paise: int) -> dict:
    side = (side or '').upper()
    product_type = (product_type or '').upper()
    turnover = quantity * price_paise
    brokerage = int(settings.FLAT_FEE_PAISE or 0)
    stt = _pct(turnover, 0.025 if (side == 'SELL' and product_type == 'MIS') else (0.1 if side == 'SELL' else 0.0)) if side == 'SELL' else 0
    # recompute stt cleanly
    if side == 'SELL':
        stt = _pct(turnover, 0.025 if product_type == 'MIS' else 0.1)
    else:
        stt = 0
    txn = _pct(turnover, 0.00297)
    sebi = _pct(turnover, 0.0001)
    if side == 'BUY':
        stamp = _pct(turnover, 0.003 if product_type == 'MIS' else 0.015)
    else:
        stamp = 0
    gst = int(round((brokerage + txn + sebi) * 0.18))
    total = brokerage + stt + txn + sebi + stamp + gst
    return {
        'brokerage': brokerage,
        'stt': stt,
        'transaction_charges': txn,
        'sebi': sebi,
        'stamp_duty': stamp,
        'gst': gst,
        'total': total,
    }
