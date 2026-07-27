<!-- EGX_PROMPT_SCHEMA: 2 -->
# EGX single-message extraction

Analyze one Egyptian stock-market Telegram source in Arabic or English. Images, ordinary text, and voice-note transcripts are equally valid source modalities.

## Source gates

Apply these gates before extracting any values:

1. Exclude a source presented as news, urgent news, breaking news, a news alert, or a news update. Indicators include `عاجل`, `خبر عاجل`, `أخبار`, `خبر`, `آخر الأخبار`, `نبأ عاجل`, `breaking news`, `urgent news`, `news alert`, `news update`, and clear semantic equivalents. Excluded news creates no recommendation, stock mention, or image observation.
2. Exclude advertisements, paid-group invitations, courses, promotions, affiliate links, greetings, memes, general commentary, and non-EGX content.
3. A recommendation requires an identifiable EGX stock and explicit actionable context such as `توصية`, `شراء`, `بيع`, `منطقة الشراء`, `نطاق الشراء`, `إشارة تداول`, recommendation, buy, sell, entry zone, or buy range.
4. Current price, support, resistance, stop loss, targets, liquidity ranking, sector ranking, or important-stock status alone is not a recommendation.
5. Never borrow a stock identity, date, recommendation cue, or value from another image or message.

Managed Include phrases extend the explicit-context vocabulary only. Managed Exclude phrases remove matching recommendation candidates. Neither can override news exclusion or stock identity.

## Value extraction

- For a single entry price, use `entry`.
- For an explicit range, set `entry` to null and preserve the visible bounds in `entry_low` and `entry_high`. Never average, reverse, round, or infer them.
- Return only TP1 as `target` and TP2 as `target_2`.
- Completely ignore TP3, target 3, third target, `مستهدف ثالث`, `الهدف الثالث`, and later targets.
- Inside a Buy recommendation, `منطقة البيع`, `نطاق البيع`, sell zone, or equivalent exit wording supplies TP1 and TP2; it does not change the signal to Sell.
- Preserve stop loss, reasoning, time horizon, indicators, and risk wording only when explicitly present.
- Do not invent prices, targets, tickers, or confidence.

## Output

Return only one JSON object:

```json
{
  "recommendations": [
    {
      "company_name": "string",
      "ticker": "string or null",
      "signal": "BUY or SELL",
      "entry": "number or null",
      "entry_low": "number or null",
      "entry_high": "number or null",
      "target": "number or null",
      "target_2": "number or null",
      "stop_loss": "number or null",
      "reason": "string or null",
      "risk_level": "string or null",
      "time_horizon": "string or null",
      "indicators": [],
      "confidence": "number from 0 to 1"
    }
  ],
  "stock_mentions": [],
  "image_observations": []
}
```

Use `stock_mentions` and `image_observations` only for qualifying non-news content. A stock mention must not be promoted into `recommendations` without explicit actionable context.
