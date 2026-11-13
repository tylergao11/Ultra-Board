"""Shared acquisition retry policy. A failed request returns to its caller."""
import time
from urllib.request import Request, urlopen, build_opener, ProxyHandler
from urllib.parse import urlencode


def request_bytes(url, *, data=None, headers=None, timeout=15, use_proxy=True):
    body=urlencode(data).encode('utf-8') if data is not None else None
    opener = urlopen if use_proxy else build_opener(ProxyHandler({})).open
    with opener(Request(url,data=body,headers=headers or {}),timeout=timeout) as response:
        return response.read()


def retry_call(operation, *, retries=3):
    started=time.perf_counter()
    for retry in range(retries+1):
        try:
            return operation(), {'attempts':retry+1,'retry_wait_seconds':retry*3,
                                 'elapsed_seconds':round(time.perf_counter()-started,3)}
        except Exception as exc:
            if retry==retries:
                exc.retry_timing={'attempts':retry+1,'retry_wait_seconds':retry*3,
                                  'elapsed_seconds':round(time.perf_counter()-started,3)}
                raise
            time.sleep(3)
