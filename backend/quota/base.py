import abc
import datetime


class UploadQuota(abc.ABC):
    """At most `limit` uploads per UTC day, counted in storage that every instance of the API shares.

    The per-minute rate limit in api.py lives in memory, so each Lambda instance or worker process has its own; this
    count is shared, so it bounds how many model calls a deployment makes in a day, however many instances run.
    """

    def __init__(self, limit: int):
        if limit < 1:
            raise ValueError(f"The daily upload limit must be at least 1, got {limit}")
        self.limit = limit

    @abc.abstractmethod
    def try_acquire(self, day: datetime.date) -> bool:
        """Count one upload on `day` if fewer than `limit` are counted already.

        The check and the count are one atomic step, so two instances can't both take the day's last upload.

        Returns:
            bool: True if the upload was counted and may go ahead, False if the day's limit is reached.
        """
        pass
