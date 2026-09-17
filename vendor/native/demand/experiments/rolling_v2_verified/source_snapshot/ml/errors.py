class DemandError(ValueError):
    code = 'validation_error'
    retryable = False

class TimeContractError(DemandError):
    code = 'time_contract_error'

class AvailabilityError(DemandError):
    code = 'input_not_available'

class WeatherContractError(DemandError):
    code = 'weather_contract_error'

class IdempotencyConflict(DemandError):
    code = 'idempotency_conflict'

class RevisionConflict(DemandError):
    code = 'revision_conflict'

class NotFound(DemandError):
    code = 'not_found'

class StorageError(DemandError):
    code = 'storage_error'
    retryable = True
