import unittest
from unittest.mock import Mock

import httpx
from openai import APITimeoutError


class LLMClientTimeoutTest(unittest.TestCase):
    def test_chat_passes_timeout_and_surfaces_timeout_error(self):
        from app.config import Config
        from app.utils.llm_client import LLMClient

        Config.LLM_API_KEY = "dummy"
        Config.LLM_BASE_URL = "http://127.0.0.1:1/v1"
        Config.LLM_MODEL_NAME = "test-model"
        Config.LLM_TIMEOUT_SECONDS = 7

        client = LLMClient()
        timeout_error = APITimeoutError(request=httpx.Request("POST", "http://127.0.0.1:1/v1/chat/completions"))
        create = client.client.chat.completions.create = Mock(side_effect=timeout_error)

        with self.assertRaises(TimeoutError) as cm:
            client.chat([{"role": "user", "content": "hello"}])

        self.assertIn("timed out after 7s", str(cm.exception))
        self.assertEqual(create.call_args.kwargs["timeout"], 7.0)


if __name__ == "__main__":
    unittest.main()
