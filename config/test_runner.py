from unittest import mock

from django.test.runner import DiscoverRunner


def _blocked(*args, **kwargs):
    raise RuntimeError("Real HTTP request attempted in tests. Mock the LLM proxy instead.")


class NoNetworkTestRunner(DiscoverRunner):
    """Fails any real HTTP request made through `requests` during the test run."""

    def run_tests(self, *args, **kwargs):
        with mock.patch("requests.sessions.Session.request", _blocked):
            return super().run_tests(*args, **kwargs)
