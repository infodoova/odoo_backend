from datetime import datetime, timezone as tz
from dateutil.relativedelta import relativedelta


FREQUENCY_DELTAS = {
    'daily':       relativedelta(days=1),
    'weekly':      relativedelta(weeks=1),
    'biweekly':    relativedelta(weeks=2),
    'monthly':     relativedelta(months=1),
    'quarterly':   relativedelta(months=3),
    'semi_annual': relativedelta(months=6),
    'annual':      relativedelta(years=1),
}


def calculate_next_send(frequency: str, from_dt: datetime) -> datetime:
    """Return the next UTC datetime to send after from_dt for the given frequency."""
    delta = FREQUENCY_DELTAS.get(frequency)
    if delta is None:
        raise ValueError(f"Unknown frequency: {frequency}")
    result = from_dt + delta
    if result.tzinfo is None:
        result = result.replace(tzinfo=tz.utc)
    return result
