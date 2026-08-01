<!-- EGX_PROMPT_SCHEMA: 5 -->
# EGX recommendation consolidation

Every source in this run has already been read. You are given the complete list of extracted
occurrences as JSON. Group them into one ranked set of stocks.

There are no images here and nothing left to judge about a source. Work only from the occurrences
supplied.

## 1. What you may not do

- Do not add a stock that is not in the input.
- Do not add, drop, average, round, repair, or move a numeric value. Every occurrence is passed
  through as it was extracted.
- Do not re-decide eligibility. Anything that failed a gate was already excluded and is not here.
- Do not merge two occurrences into one. They stay separate inside `data_points`.

## 2. Grouping

Group by exact `stock_code`. Two occurrences of one code belong to one stock however many sources
or images they came from.

Carry `stock_name_en` and `stock_name_ar` from the occurrences. Where they disagree, use the most
complete value and never invent a third.

## 3. Ranking

- `mention_count` equals the number of `data_points` for that stock.
- Rank by `mention_count`, highest first.
- Break a tie with the better risk-to-target profile, then with the earlier `date`.
- Rank consecutively from 1, with no gaps.

A stock mentioned by several independent sources is a stronger signal than one mentioned once, and
the ranking is the only place that judgement is expressed.

## 4. Arabic summary

Write exactly one `notes_summary` per stock, in Arabic, from that stock's occurrences alone.

- Preserve useful and genuinely different insights.
- Merge duplicate or semantically equivalent meanings, and mention each meaning once.
- Do not name a stock, date, or source that is not among that stock's occurrences.
- Keep source-specific evidence and values in `data_points`, not in the summary.
- Keep it under 60 Arabic words.

## 5. Categories

Populate `text_based_categories` only with stock codes present in the final ranked rows.

- `watchlist_stocks`: stocks whose occurrences are `destination: watching`.
- `most_important_stocks`: the highest-ranked main-destination stocks.
- `trading_stocks`: main-destination stocks presented for trading between sessions.

## 6. JSON contract

Return only one JSON object. Copy each occurrence into `data_points` with every field it arrived
with, unchanged.

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
  "text_based_categories": {
    "most_important_stocks": [],
    "trading_stocks": [],
    "watchlist_stocks": []
  }
}
```

## 7. Final invariants

Before returning JSON, confirm:

- Every occurrence supplied appears in exactly one stock's `data_points`.
- No `source_message_id` or `source_image_ref` differs from the value it arrived with.
- Ranks run 1..n with no gaps and no duplicates.
- Every code in `text_based_categories` is a code you returned.
