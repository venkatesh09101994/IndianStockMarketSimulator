/**
 * Client-side estimate of the charges the backend applies to one executed leg.
 *
 * Mirrors backend/app/services/charges.py (flat brokerage defaults to 0):
 *   - STT: 0.1% on CNC sell, 0.025% on MIS sell
 *   - NSE transaction charges: 0.00297% on turnover
 *   - SEBI turnover fee: 0.0001% on turnover
 *   - Stamp duty: 0.015% on CNC buy, 0.003% on MIS buy
 *   - GST: 18% on (brokerage + transaction charges + SEBI)
 */
export function estimateCharges(
  side: 'BUY' | 'SELL',
  productType: 'CNC' | 'MIS',
  quantity: number,
  price: number
): number {
  if (!Number.isFinite(quantity) || !Number.isFinite(price) || quantity <= 0 || price <= 0) {
    return 0;
  }

  const turnoverPaise = Math.round(quantity * price * 100);
  const pct = (amountPaise: number, percent: number) => Math.round((amountPaise * percent) / 100);

  const stt = side === 'SELL' ? pct(turnoverPaise, productType === 'MIS' ? 0.025 : 0.1) : 0;
  const stamp = side === 'BUY' ? pct(turnoverPaise, productType === 'MIS' ? 0.003 : 0.015) : 0;
  const txn = pct(turnoverPaise, 0.00297);
  const sebi = pct(turnoverPaise, 0.0001);
  const gst = Math.round((txn + sebi) * 0.18);

  return (stt + stamp + txn + sebi + gst) / 100;
}
