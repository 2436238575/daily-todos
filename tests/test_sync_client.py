from __future__ import annotations

import unittest

from core.sync_client import _sanitize_error_detail


class SyncClientSanitizationTest(unittest.TestCase):
    def test_sanitize_fastapi_password_input(self) -> None:
        detail = (
            '{"detail":[{"type":"string_too_short","loc":["body","password"],'
            '"msg":"String should have at least 1 character","input":"secret"}]}'
        )

        sanitized = _sanitize_error_detail(detail)

        self.assertIn('"input": "***"', sanitized)
        self.assertNotIn("secret", sanitized)
        self.assertIn("string_too_short", sanitized)

    def test_sanitize_token_fields(self) -> None:
        sanitized = _sanitize_error_detail('{"refresh_token":"abc","message":"bad"}')

        self.assertIn('"refresh_token": "***"', sanitized)
        self.assertIn('"message": "bad"', sanitized)
        self.assertNotIn("abc", sanitized)


if __name__ == "__main__":
    unittest.main()
