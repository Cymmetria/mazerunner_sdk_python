class APIException(Exception):
    def __init__(self, response_code, *args, **kwargs):
        self.response_code = response_code
        super(APIException, self).__init__(*args, **kwargs)


class ValidationError(APIException):
    pass


class ServerError(APIException):
    pass
