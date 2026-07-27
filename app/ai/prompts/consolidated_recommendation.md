<!-- EGX_PROMPT_SCHEMA: 2 -->
# EGX consolidated recommendation analysis

Analyze the supplied Egyptian stock-market Telegram sources as one Results run. Images, ordinary text messages, and voice-note transcripts are equally valid source modalities. Apply the gates below independently to each source item before extracting stock identities or values.

## 1. Highest-priority exclusions

Exclude an entire source item when it is presented as news, urgent news, breaking news, a news alert, or a news update. Indicators include `عاجل`, `خبر عاجل`, `أخبار`, `خبر`, `آخر الأخبار`, `نبأ عاجل`, `breaking news`, `urgent news`, `news alert`, `news update`, and clear semantic equivalents. Exclude it even when it names a stock, contains prices or percentages, discusses market movement, or resembles a recommendation.

Also exclude advertisements, invitations, courses, promotions, links, disclaimers, greetings, memes, general commentary, non-EGX material, previous or achieved recommendations, target-hit updates, and content that is no longer actionable.

An excluded source must create nothing in any output array, category, count, Notes field, or source link. Managed Include phrases never override these exclusions.

For a Telegram message containing several images, judge each image independently. Exclude only the news image unless the message text or voice transcript makes the entire message a news item.

## 2. Hard date gate

`TARGET_DATE` is supplied in the runtime context.

For every ordinary recommendation:

1. Read the date explicitly printed or stated inside that same source item.
2. Parse it without changing, advancing, translating, repairing, or inferring it.
3. Keep the recommendation only when that source date equals `TARGET_DATE` exactly.
4. Exclude it when the date is missing, unreadable, ambiguous, earlier, later, or different by even one day.
5. Never use a Telegram posting timestamp, nearby source, timing wording, or intended future session to override the source date.
6. For an image, only a date visible inside that image is valid.

Examples for `TARGET_DATE: 2026-07-28`:

- Image says `27/07/2026` → exclude.
- Image says `28/07/2026` → eligible for later gates.
- Image has no readable date → exclude.
- Telegram post is dated 28/7 but its image says 27/7 → exclude.

For an eligible ordinary recommendation, return:

- `date`: `TARGET_DATE`
- `effective_date_basis`: `explicit_date`
- `visible_source_date`: the exact visible source date
- `date_evidence`: the exact same-source date phrase
- `timing_evidence`: null

Never set `date` to `TARGET_DATE` to repair a mismatched `visible_source_date`.

## 3. Destination classification

Assign each eligible source to exactly one destination:

### Main recommendation

Requires an identifiable EGX stock and explicit actionable context such as `توصية`, `شراء`, `بيع`, `منطقة الشراء`, `نطاق الشراء`, `إشارة تداول`, recommendation, buy, sell, entry zone, or buy range.

Current price, support, resistance, stop loss, targets, liquidity ranking, sector ranking, important-stock status, a ticker list, or general technical discussion alone is not a recommendation.

### Watching

Use `effective_date_basis: watching` only when the same source explicitly identifies that exact stock as `سهم تحت المراقبة`, `تحت المراقبة`, `سهم للمراقبة`, watching, under watch, stock to watch, or a clear semantic equivalent.

- Copy the exact watch wording into `timing_evidence`.
- Preserve conditional actions such as buy on breakout and all explicit levels.
- A watch heading may govern the ticker immediately beneath it in the same image card.
- For a Watching image, require a visible image date inside the supplied analysis period; never substitute the Telegram timestamp.
- For Watching text or a voice transcript without an internal date, the supplied `MESSAGE DATE` may become `visible_source_date` and `date_evidence`.
- Return `date` as `TARGET_DATE`.

Never apply Watching date flexibility to an ordinary recommendation.

### Client inquiry

Content explicitly presented as a reply to a customer or member question, including `ردًا على استفسارات عملائنا`, `ردا على استفسارات عملائنا`, `رد على استفسار`, and `استفسارات العملاء`, belongs only in `client_inquiry_responses`.

Never place the same Telegram ID in both a recommendation and an inquiry. Do not classify a normal recommendation as an inquiry merely because the same channel posted inquiries elsewhere.

### Excluded

Everything that fails these gates is excluded. Do not return general stock mentions or image observations in consolidated analysis.

## 4. Source traceability

- `source_message_id` must exactly equal the supporting `TELEGRAM_ID`.
- Do not return a channel name; the application restores it locally.
- For image evidence, `source_image_ref` must equal the immutable `IMAGE_REF` immediately associated with that image.
- For text-only or voice-only evidence, `source_image_ref` must be null.
- `recommendation_evidence` must be a short exact actionable cue from the same source. It does not need to contain the ticker when the source layout places the ticker and cue separately.
- Never copy an image reference, stock identity, evidence phrase, date, or value from a neighboring source.

## 5. Price and target extraction

- Use `buy_price` for one entry price.
- For an explicit entry range, set `buy_price` to null and preserve the visible bounds in `buy_price_low` and `buy_price_high`. Never average, reverse, round, or infer them.
- Return only TP1 in `target_1` and TP2 in `target_2`.
- Completely ignore TP3, target 3, third target, take profit 3, `مستهدف ثالث`, `الهدف الثالث`, and every later target in all fields and summaries.
- Inside a Buy recommendation, `منطقة البيع`, `نطاق البيع`, sell zone, or equivalent exit wording supplies TP1 and TP2; it does not make the recommendation a Sell.
- Pair explicit `عائد الربح` or profit-return percentages with their corresponding target in `return_tp1_pct` and `return_tp2_pct`.
- If a return percentage is not explicitly visible, return null. The application calculates the fallback.
- Preserve explicit stop loss, support, resistance, and risk values.
- Do not invent or transfer values.

## 6. Arabic Notes

Group all accepted recommendation occurrences by exact `stock_code` before writing `notes_summary`.

- Write exactly one concise, factual Arabic summary per stock.
- Merge duplicate and semantically equivalent meanings.
- Preserve genuinely different insights such as Watching, entry range, TP1, TP2, stop loss, and risk warnings.
- Mention each meaning once.
- Do not paste or enumerate full messages, captions, tables, or image text.
- Keep source-specific evidence and values only in `data_points`.
- Keep the summary under 60 Arabic words.

## 7. JSON contract

Return only one JSON object with this structure:

```json
{
  "analysis_period": "string",
  "top_consolidated_recommendations": [
    {
      "stock_code": "English EGX ticker",
      "stock_name_en": "string",
      "stock_name_ar": "string or null",
      "mention_count": "integer",
      "rank": "integer",
      "notes_summary": "concise Arabic string",
      "data_points": [
        {
          "date": "YYYY-MM-DD",
          "effective_date_basis": "explicit_date or watching",
          "visible_source_date": "string or null",
          "date_evidence": "string or null",
          "timing_evidence": "string or null",
          "source_message_id": "exact TELEGRAM_ID",
          "source_image_ref": "integer or null",
          "recommendation_evidence": "exact same-source cue",
          "recommendation_type": "buy or sell",
          "buy_price": "number or null",
          "buy_price_low": "number or null",
          "buy_price_high": "number or null",
          "target_1": "number or null",
          "return_tp1_pct": "number or null",
          "target_2": "number or null",
          "return_tp2_pct": "number or null",
          "stop_loss": "number or null",
          "support": "number or null",
          "resistance": "number or null",
          "risk_pct": "number or null",
          "notes_ar": "concise Arabic string or null"
        }
      ]
    }
  ],
  "achieved_targets": [],
  "client_inquiry_responses": [
    {
      "stock_code": "English EGX ticker",
      "stock_name_en": "string",
      "stock_name_ar": "string or null",
      "date": "YYYY-MM-DD or null",
      "source_message_id": "exact TELEGRAM_ID",
      "source_image_ref": "integer or null",
      "source_excerpt": "exact excerpt or null",
      "question_summary_ar": "string or null",
      "reply_summary_ar": "string or null",
      "current_trend_ar": "string or null",
      "last_price": "number or null",
      "buy_price": "number or null",
      "buy_price_low": "number or null",
      "buy_price_high": "number or null",
      "target_1": "number or null",
      "target_2": "number or null",
      "stop_loss": "number or null",
      "support": "number or null",
      "resistance": "number or null",
      "advice_ar": "string or null",
      "alternate_scenario_ar": "string or null"
    }
  ],
  "text_based_categories": {
    "most_important_stocks": [],
    "trading_stocks": [],
    "watchlist_stocks": []
  },
  "daily_breakdown": {}
}
```

`achieved_targets` remains empty because previous and target-hit sources are excluded from this active recommendation run. Populate `text_based_categories` and `daily_breakdown` only from accepted main or Watching rows; never use excluded general mentions.

## 8. Final invariants

Before returning JSON, delete any row that fails:

- It is not news or other excluded content.
- Its Telegram ID belongs to its own source.
- It has an identifiable EGX stock.
- It has explicit recommendation context or explicit same-stock Watching context.
- An `explicit_date` row has `date == TARGET_DATE`, a parseable `visible_source_date == TARGET_DATE`, matching `date_evidence`, and `timing_evidence == null`.
- A `watching` row has exact same-source watch wording in `timing_evidence`.
- Its values and image reference come from that same source.
- It appears in exactly one destination.

Delete invalid rows before grouping, ranking, counting mentions, creating categories, or writing Notes. Return JSON only.
