# Pricing reference and assumptions

**Checked:** 2026-10-26

**Official public reference:** [OpenAI API pricing](https://developers.openai.com/api/docs/pricing)
**Reasoning-token billing reference:** [OpenAI reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)

The OpenAI standard-pricing table lists `gpt-6-luna` at **$0.10 per million input tokens**, **$0.50 per million output tokens**, and **$0.01 per million cached input tokens**. Those are public OpenAI API prices. I did not find a university Portkey rate card, Portkey billing export, or course-gateway invoice, so these are an **illustrative pricing assumption**, not confirmed university charges.

All task estimates use:

```text
estimated USD = (input_tokens × $0.10 + output_tokens × $0.50) / 1,000,000
```

The OpenAI reasoning guide states that reasoning tokens are billed as output tokens. `output_tokens` is therefore charged once; the separately reported `reasoning_tokens` field is a subset and is not added again. The Phase 2.4 usage export also explicitly records that output tokens include reasoning tokens.

The SQLite usage schema does not record cached-input token counts. No cached-input discount is applied. Failed attempts with missing token counts are excluded from token-based dollar totals; they are not assumed to be free. The historical estimate includes all 40 logged attempts with token data, including two incomplete output-limit attempts, but it cannot be reconciled to university billing.
