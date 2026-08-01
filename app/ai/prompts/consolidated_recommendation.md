<!-- EGX_PROMPT_SCHEMA: 5 -->
# EGX recommendation extraction

Extract from the supplied Egyptian stock-market Telegram sources.

This request carries one slice of a larger run. Read only what is here: do not rank stocks, count
mentions, or write a per-stock summary, and never mention a source you were not given. A second
pass consolidates every slice once they are all read.

Images, ordinary text messages, and voice-note transcripts are equally valid source modalities. Apply the following gates independently to every source item before extracting stock identities or values.

Do not repair, advance, infer, or borrow dates, stock identities, evidence, image references, or prices.

Managed Include phrases extend recommendation wording only. They never override exclusions, date eligibility, source isolation, or destination separation.

## 1. Highest-priority exclusions

Exclude an entire source item when it is presented as news, urgent news, breaking news, a news alert, or a news update.

Indicators include:

- `عاجل`
- `خبر عاجل`
- `أخبار`
- `خبر`
- `آخر الأخبار`
- `نبأ عاجل`
- `breaking news`
- `urgent news`
- `news alert`
- `news update`
- Clear semantic equivalents

Exclude news content even when it names a stock, contains prices or percentages, discusses market movement, or resembles a recommendation.

Also exclude:

- Advertisements
- Invitations
- Courses
- Promotions
- Links
- Disclaimers
- Greetings
- Memes
- General commentary
- Non-EGX material
- Previous or achieved recommendations
- Target-hit updates
- Follow-ups on an earlier call, including `توصية سابقة`, `التوصية السابقة`, `متابعة`, `تحديث`
- A screenshot or forward of an older recommendation, whatever the day it was posted
- Content that is no longer actionable
- Liquidity rankings without an actionable recommendation
- Sector rankings and sector-summary content
- `أهم القطاعات`
- `أنشط القطاعات`
- `أهم سهم لكل قطاع`
- `مؤشر قطاع`
- `مؤشرات القطاعات`
- `أداء القطاعات`
- Clear semantic equivalents of these sector-ranking headings

A sector is not a stock. Exclude any section whose heading names a sector index, a sector ranking, or sector performance, and never return a sector code, sector index, or sector name in `stock_code`, `stock_name_en`, or `stock_name_ar`. This holds even when the section lists prices, percentages, targets, support, resistance, or a table shaped like a recommendation.

A sector named inside an otherwise valid stock recommendation, describing which sector that stock belongs to, does not make the recommendation sector content.

`أهم الأسهم اليوم` is not a sector-ranking heading and remains eligible under the Main recommendation rule.

For an image containing multiple distinct sections, judge each section independently.

For a Telegram message containing several images, judge each image independently. Exclude only the invalid image unless the message text or voice transcript makes the entire message invalid.

Text accompanying an image is evidence about that image. When a caption marks the image as a past, previous, or already-achieved recommendation - `توصية سابقة`, `التوصية السابقة`, or a clear equivalent - exclude the image it belongs to, even when the image itself looks like a fresh recommendation card.

An excluded item or section must create nothing in `top_consolidated_recommendations`, any
category, count, Notes field, or source link.

Record it in `excluded` instead, with the stock code where there is one, the date you read, and the
reason. That array is the only place an exclusion may appear, and it is how the exclusion is shown
to have happened rather than merely assumed.

## 2. Hard date gate

`TARGET_DATE` is supplied in the runtime context.

Apply this date gate to every Main or Watching recommendation, regardless of whether its source is an image, text message, or voice-note transcript.

1. Read the date explicitly printed or stated inside that exact source item.
2. Parse it without changing, advancing, repairing, or inferring it.
3. Keep the recommendation only when the source date equals `TARGET_DATE` exactly.
4. Exclude it when the date is missing, unreadable, ambiguous, earlier, later, or different by even one day.
5. Never use a Telegram posting timestamp, nearby source, timing wording, or intended future session as a substitute.
6. For an image, only a date visibly printed inside that image is valid.
7. For text or voice, only a date explicitly stated in that text or transcript is valid.

Examples for `TARGET_DATE: 2026-07-29`:

- Source says `28/07/2026` → exclude.
- Source says `29/07/2026` → eligible for later gates.
- Source has no readable date → exclude.
- Telegram post is dated 29/7 but its image says 28/7 → exclude.
- Telegram post is dated 29/7 but its image says 13/7 → exclude. An old card re-posted today is still an old card.

A date that does not equal `TARGET_DATE` excludes the recommendation outright. It is never reported with `date` set to `TARGET_DATE` and the real date left in `visible_source_date`: that returns an excluded recommendation wearing the target date, which is worse than returning nothing.

For every recommendation you return:

- `date`: the session **you** judge the recommendation is for, read from the source. Not a copy of
  `TARGET_DATE`. If the source names 30 July, `date` is `2026-07-30` even when `TARGET_DATE` is
  `2026-07-29`.
- `visible_source_date`: the exact visible or stated source date
- `date_evidence`: the exact same-source date phrase

`date` and `TARGET_DATE` disagreeing is not an error to hide. It is how you say the source belongs
to a different session, and it is checked. Copying `TARGET_DATE` into `date` while the real date
sits in `visible_source_date` reports a recommendation you have already judged ineligible as though
it qualified.

## 3. Destination classification

Assign every eligible source item or independent image section to exactly one destination.

### Main recommendation

A Main recommendation requires:

- An identifiable EGX stock
- Explicit actionable recommendation context

Examples include:

- `توصية`
- `شراء`
- `بيع`
- `منطقة الشراء`
- `نطاق الشراء`
- `إشارة تداول`
- `recommendation`
- `buy`
- `sell`
- `entry zone`
- `buy range`
- Clear semantic equivalents

Current price, support, resistance, stop loss, targets, liquidity ranking, sector ranking, important-stock status, a ticker list, or general technical discussion alone is not a recommendation.

The exact heading `أهم الأسهم اليوم` is explicit recommendation context; extract every stock row from the table directly beneath it.

For a Main recommendation, return:

- `effective_date_basis`: `explicit_date`
- `timing_evidence`: null

### Watching

Use `effective_date_basis: watching` only when the same source explicitly identifies that exact stock using wording such as:

- `سهم تحت المراقبة`
- `سهم المراقبة`
- `تحت المراقبة`
- `سهم للمراقبة`
- `watching`
- `under watch`
- `stock to watch`
- A clear semantic equivalent

Requirements:

- The source date must equal `TARGET_DATE` exactly.
- Copy the exact Watching wording into `timing_evidence`.
- Preserve conditional actions such as buying on a breakout.
- Preserve all explicitly stated levels.
- A Watching heading may govern the ticker immediately beneath it in the same image card.
- Do not apply Watching wording from one stock or section to another.

### Main and Watching sections in one image

Scan the entire image from top to bottom and analyze every distinct section independently. Do not stop after the first recommendation panel.

When `أهم الأسهم اليوم` appears below another recommendation or Watching card, also extract every valid stock row from the table directly beneath that heading.

Return a separate `data_point` for every valid section, including when the same stock appears in more than one section. Never combine or transfer values across sections. The application consolidates exact same-stock and same-image occurrences after extraction.

### Client inquiry

Content explicitly presented as a reply to a customer or member question belongs only in `client_inquiry_responses`.

Examples include:

- `ردًا على استفسارات عملائنا`
- `ردا على استفسارات عملائنا`
- `رد على استفسار`
- `استفسارات العملاء`

Do not classify a normal recommendation as an inquiry merely because the same channel posts inquiry replies elsewhere.

### Excluded

Everything that fails these gates is excluded.

Do not return general stock mentions or image observations in consolidated analysis.

## 4. Source traceability

- `source_message_id` must exactly equal the supporting `TELEGRAM_ID`.
- Do not return a channel name; the application restores it locally.
- For image evidence, `source_image_ref` must equal the immutable `IMAGE_REF` announced immediately before that exact image, in this request.
- `IMAGE_REF` numbering restarts at 1 in every request. Cite only the numbers announced here; a number outside that range belongs to an image you were not given.
- Every `IMAGE_REF` announced in this request must appear at least once, in `extracted` or in `excluded`. An image you decide against is excluded with a reason, never left out.
- For text-only or voice-only evidence, `source_image_ref` must be null.
- `recommendation_evidence` must be a short, exact actionable cue from that same source.
- Never copy an image reference, stock identity, evidence phrase, date, or value from a neighboring source, image, section, or stock row.

## 5. Stock-row and table-column isolation

For every table:

1. Locate one exact ticker row.
2. Confirm that the company name belongs to that ticker.
3. Read each value only at the intersection of that ticker row and its visible column heading.
4. Finish that ticker row before processing another ticker.
5. Return null when a cell is missing, unreadable, ambiguous, or cannot be confidently mapped.
6. Never shift values left or right.
7. Never reuse one numeric row for another stock.
8. Never use values from a row above or below the selected ticker.

Use these mappings when present:

- `منطقة الشراء` or `نطاق الشراء` → Entry or entry range
- `الدعم` → Support
- `المقاومة` → Resistance
- `الهدف الأول` or `مستهدف أول` → TP1
- First corresponding `عائد الربح` → TP1 Return %
- `الهدف الثاني` or `مستهدف ثاني` → TP2
- Second corresponding `عائد الربح` → TP2 Return %
- `وقف الخسارة` → Stop
- `عائد المخاطرة` → Risk %

Support and resistance are not targets unless the source explicitly labels them as targets.

A current or closing price is not an entry unless the source explicitly presents it as an entry or purchase price.

## 6. Price and target extraction

- Use `buy_price` for one explicit entry price.
- For an explicit entry range, set `buy_price` to null.
- Preserve the visible range bounds in `buy_price_low` and `buy_price_high`.
- Never average, reverse, round, or infer entry bounds.
- Return only TP1 in `target_1`.
- Return only TP2 in `target_2`.
- Ignore every third or later target in all output fields and summaries.
- Inside a Buy recommendation, `منطقة البيع`, `نطاق البيع`, sell zone, or equivalent exit wording supplies TP1 and TP2; it does not change the recommendation to Sell.
- Pair explicit profit-return percentages with their corresponding targets.
- If a return percentage is not explicitly visible, return null. The application calculates the fallback.
- Preserve explicit stop loss, support, resistance, and risk values.
- Do not invent, calculate, transfer, or repair source values.

## 7. Arabic Notes

Write `notes_ar` for one occurrence from that occurrence alone.

Requirements:

- Keep it concise, factual, and specific to this source.
- Do not include rejected dates, excluded sources, excluded sections, neighboring stocks, or deleted rows.
- Do not paste full messages, captions, tables, or image text.
- Do not summarise across occurrences or across stocks. The consolidation pass does that from what
  you return here, and it can only work with occurrences you kept separate.

## 8. JSON contract

Return only one JSON object using this structure. One `extracted` entry is one occurrence in one
source: a stock named twice in two images is two entries, not one merged entry.

```json
{
  "extracted": [
    {
      "stock_code": "English EGX ticker",
      "stock_name_en": "string",
      "stock_name_ar": "string or null",
      "date": "YYYY-MM-DD, the session the source is for",
      "effective_date_basis": "explicit_date or watching",
      "visible_source_date": "string or null",
      "date_evidence": "string or null",
      "timing_evidence": "string or null",
      "source_message_id": "exact TELEGRAM_ID",
      "source_image_ref": "integer or null",
      "recommendation_evidence": "exact same-source cue",
      "recommendation_type": "buy or sell",
      "destination": "main or watching",
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
  ],
  "excluded": [
    {
      "stock_code": "English EGX ticker or null",
      "source_message_id": "exact TELEGRAM_ID",
      "source_image_ref": "integer or null",
      "visible_source_date": "string or null",
      "reason": "news | sector | past_recommendation | wrong_session | not_a_recommendation | no_date"
    }
  ],
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
  ]
}
```

Additional contract rules:

- `destination` is `watching` for a stock classified as Watching and `main` otherwise.
- Do not merge two occurrences of one stock, even from the same image. Consolidation needs them apart.
- Everything excluded appears in `excluded`, with the date you read and why it was dropped.

## 9. Final invariants

Before returning JSON, delete every row that fails any of these checks:

- It is not news or another excluded content type.
- It is not from a sector-ranking section.
- Its Telegram ID belongs to its exact source.
- Its image reference is one announced in this request, and belongs to that Telegram message.
- It has an identifiable EGX stock.
- It has explicit recommendation context or exact same-stock Watching context.
- Its visible or stated source date equals `TARGET_DATE`.
- Its `date_evidence` comes from that exact source.
- A Main row has `effective_date_basis: explicit_date` and `timing_evidence: null`.
- A Watching row has exact same-source Watching wording in `timing_evidence`.
- Its stock identity and values come from the same ticker row.
- Its values and image reference come from the same source.
- It appears in exactly one destination.
- Its Notes and categories use only accepted rows.

Delete invalid rows before grouping, ranking, counting mentions, creating categories, or writing Notes.

Return JSON only.
