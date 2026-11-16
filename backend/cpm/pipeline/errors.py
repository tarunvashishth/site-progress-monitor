class PermanentError(Exception):
    """Retrying will not help (bad video, AI not configured, invalid config). Job fails immediately."""


class TransientError(Exception):
    """Might succeed later (network, 5xx, rate limit). Job is re-queued until attempts run out."""
