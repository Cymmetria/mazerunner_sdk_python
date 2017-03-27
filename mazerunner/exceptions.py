class APIException(Exception):
    def __init__(self, response_code, *args, **kwargs):
        self.response_code = response_code
        super(APIException, self).__init__(*args, **kwargs)


class BadParamError(RuntimeError):
    """
    This will be raised when a given param is of the wrong type, or it's incompatible with the
    requested resource
    """
    pass


class InvalidInstallMethodError(RuntimeError):
    """
    This will be raised when an invalid installation method is selected for deployment
    """
    pass


class ValidationError(APIException):
    """
    This will be raised when the server denies the request, typically a 4xx response
    """
    pass


class ServerError(APIException):
    """
    This will be raised when the server could not complete the request. Typically a 5xx response
    """
    pass


