import time


class TimeoutException(Exception):
    pass


def wait_until(func,
               check_return_value=True,
               total_timeout=60,
               interval=0.5,
               exc_list=None,
               error_message="",
               *args,
               **kwargs):
    """
    Waits until func(*args, **kwargs),
    until total_timeout seconds,
    for interval seconds interval,
    while catching exceptions given in exc_list.
    """
    start_function = time.time()
    while time.time() - start_function < total_timeout:

        try:
            return_value = func(*args, **kwargs)
            if not check_return_value or (check_return_value and return_value):
                return

        except Exception as e:
            if exc_list and any([isinstance(e, x) for x in exc_list]):
                pass
            else:
                raise

        time.sleep(interval)

    raise TimeoutException, error_message
