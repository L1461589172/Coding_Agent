class HistoryError(RuntimeError):
    code = "HISTORY_STORAGE_UNAVAILABLE"


class HistoryStorageUnavailable(HistoryError):
    code = "HISTORY_STORAGE_UNAVAILABLE"


class HistoryLockUnavailable(HistoryStorageUnavailable):
    pass


class HistoryFormatUnsupported(HistoryError):
    code = "HISTORY_FORMAT_UNSUPPORTED"


class HistoryDataInvalid(HistoryError):
    code = "HISTORY_DATA_INVALID"


class HistoryCapacity(HistoryError):
    code = "HISTORY_CAPACITY"


class SessionNotFound(HistoryError):
    code = "SESSION_NOT_FOUND"


class SessionTaskLimit(HistoryCapacity):
    code = "SESSION_TASK_LIMIT"


class SessionActive(HistoryError):
    code = "SESSION_ACTIVE"
