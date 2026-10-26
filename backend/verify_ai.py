from __future__ import annotations

import json
import sys

from backend.ai_service import AI_MODEL, AIService, AIServiceError


def main() -> int:
    try:
        result = AIService().generate(
            "Reply with exactly: homi API connected.",
            purpose="verification",
            reasoning_effort="medium",
            max_output_tokens=32,
        )
    except AIServiceError as error:
        print(
            json.dumps(
                {
                    "success": False,
                    "model": AI_MODEL,
                    "error_code": error.code,
                    "http_status": error.http_status,
                },
                indent=2,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "success": True,
                "requested_model": AI_MODEL,
                "response_model": result.model,
                "reasoning_effort": result.reasoning_effort,
                "response": result.text,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "reasoning_tokens": result.reasoning_tokens,
                "latency_ms": result.latency_ms,
                "request_id": result.request_id,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
