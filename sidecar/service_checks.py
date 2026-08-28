# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#     "fastapi>=0.110",
# ]
# ///
"""The request gate: auth, size limits, concurrency, error mapping.

Run: uv run --script service_checks.py     (or: python3 devrunner.py service_checks.py)

Everything the app relies on *before* a sentence reaches the parser lived
untested: the Swift side asserts its half of the protocol (SidecarProtocolTests,
SidecarLifecycleTests) but nothing on this side asserted that a wrong token is
actually refused.  An auth check that silently stopped refusing would pass every
other suite in this repo.

No model and no torch: ``server`` defers those imports into ``load()``, which is
never called here, so this suite needs only fastapi and runs in milliseconds --
which is what lets CI run it on every push.  A guard that can only be checked on
the one machine with 3.2 GB of weights installed is a guard that gets checked
when someone remembers.  ``parse_text`` is stubbed wherever a test is about the
gate rather than about parsing.

Still deliberately *not* named ``test_*.py``: ``python -m unittest discover -s
sidecar`` must stay dependency-free, and this needs fastapi for HTTPException.
"""
from __future__ import annotations

import unittest
from unittest import mock

import server
from fastapi import HTTPException
from pydantic import ValidationError


class RequireAuthTests(unittest.TestCase):
    """A one-time token is the only thing standing between a local sidecar and
    any other process on the machine that can reach 127.0.0.1."""

    def assert_rejected(self, presented: str | None) -> None:
        with self.assertRaises(HTTPException) as caught:
            server.require_auth(presented)
        self.assertEqual(caught.exception.status_code, 401)

    def test_correct_token_is_accepted(self):
        with mock.patch.object(server, "auth_token", "s3cret"):
            self.assertIsNone(server.require_auth("s3cret"))

    def test_wrong_token_is_refused(self):
        with mock.patch.object(server, "auth_token", "s3cret"):
            self.assert_rejected("s3cre")     # prefix
            self.assert_rejected("s3crett")   # extension
            self.assert_rejected("S3CRET")    # case
            self.assert_rejected("")
            self.assert_rejected(None)

    def test_unset_server_token_refuses_everyone(self):
        """Fail closed. If the token were ever empty at runtime, comparing ""
        against a missing header would otherwise read as a match and open the
        parser to anything that can guess the port."""
        with mock.patch.object(server, "auth_token", ""):
            self.assert_rejected("")
            self.assert_rejected(None)
            self.assert_rejected("anything")


class ParseRequestTests(unittest.TestCase):
    def test_bounds_are_enforced_by_the_model(self):
        with self.assertRaises(ValidationError):
            server.ParseRequest(text="")
        with self.assertRaises(ValidationError):
            server.ParseRequest(text="x" * 12_001)
        self.assertEqual(server.ParseRequest(text="Hi.").text, "Hi.")


class ParseGateTests(unittest.TestCase):
    """The token ceiling, the busy signal, and the ValueError -> 422 mapping
    the Swift client distinguishes (SidecarFailure.rejected vs .busy)."""

    def setUp(self):
        # A slot leaked by one test would make the next one look "busy".
        self.assertEqual(server.parse_slots._value, 2)

    def test_oversized_input_is_refused_before_the_model_runs(self):
        long_text = " ".join(["word"] * 513)
        with (mock.patch.object(server, "parse_text") as parse_text,
                self.assertRaises(HTTPException) as caught):
            server.parse(server.ParseRequest(text=long_text))
        self.assertEqual(caught.exception.status_code, 422)
        parse_text.assert_not_called()
        # Refused before acquiring: an oversized request must not be able to
        # occupy one of the two slots.
        self.assertEqual(server.parse_slots._value, 2)

    def test_input_at_the_ceiling_still_parses(self):
        at_limit = " ".join(["word"] * 511) + " ."
        with mock.patch.object(server, "parse_text", return_value=([], [])):
            server.parse(server.ParseRequest(text=at_limit))

    def test_busy_sidecar_answers_429(self):
        self.assertTrue(server.parse_slots.acquire(blocking=False))
        self.assertTrue(server.parse_slots.acquire(blocking=False))
        try:
            with (mock.patch.object(server, "parse_text") as parse_text,
                    self.assertRaises(HTTPException) as caught):
                server.parse(server.ParseRequest(text="A sentence."))
            self.assertEqual(caught.exception.status_code, 429)
            parse_text.assert_not_called()
        finally:
            server.parse_slots.release()
            server.parse_slots.release()

    def test_a_sentence_failure_is_422_and_frees_its_slot(self):
        """R-002: a single bad sentence must not read as a dead engine, and it
        must not cost a slot -- two of them would wedge the sidecar shut."""
        boom = mock.Mock(side_effect=ValueError("teaching tree does not cover"))
        with (mock.patch.object(server, "parse_text", boom),
                self.assertRaises(HTTPException) as caught):
            server.parse(server.ParseRequest(text="A sentence."))
        self.assertEqual(caught.exception.status_code, 422)
        self.assertIn("does not cover", caught.exception.detail)
        self.assertEqual(server.parse_slots._value, 2)

    def test_an_unexpected_failure_also_frees_its_slot(self):
        """Only ValueError is mapped to 422; anything else becomes a 500. It
        still has to release, or the second crash leaves one slot and the third
        leaves none."""
        with (mock.patch.object(server, "parse_text", side_effect=RuntimeError),
                self.assertRaises(RuntimeError)):
            server.parse(server.ParseRequest(text="A sentence."))
        self.assertEqual(server.parse_slots._value, 2)

    def test_a_served_request_resets_the_idle_clock(self):
        with mock.patch.object(server, "last_request", 0.0):
            with mock.patch.object(server, "parse_text", return_value=([], [])):
                server.parse(server.ParseRequest(text="A sentence."))
            self.assertGreater(server.last_request, 0.0)


class HealthTests(unittest.TestCase):
    def test_health_advertises_the_parse_protocol_version(self):
        """`probeHealth` refuses a sidecar whose version it does not read, so a
        renamed or missing key takes the engine down rather than mis-decode."""
        payload = server.health()
        self.assertEqual(payload["parseProtocolVersion"], server.PARSE_PROTOCOL_VERSION)

    def test_health_reports_not_ok_until_the_model_is_loaded(self):
        """`ensureHealthy` polls this to tell "still loading" from "ready"; a
        health check that said ok before load() would send the first sentence
        into a None pipeline."""
        with mock.patch.object(server, "nlp", None):
            self.assertFalse(server.health()["ok"])
        with mock.patch.object(server, "nlp", object()):
            self.assertTrue(server.health()["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
