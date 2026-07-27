# Note — boredom column float-precision artifact (data quality)

**Found during:** notion-cycle search content testing.

**Symptom:** `brain_subtopic.boredom` (and likely `brain_interaction.boredom`) stores
full double-precision floats, e.g. `0.200000000000000011102230246251565404236316680908203125`
instead of a clean `0.20`. Should be 2-decimal.

**Impact:** mostly cosmetic — comparisons (`boredom >= 0.2`) still work correctly. But
it's ugly in queries, risks subtle float-equality issues, and isn't the intended
precision.

**Likely cause:** the value is written by the Airtable sync without rounding, into a
`double precision` (or unrounded `numeric`) column.

**Fix options (separate task — Airtable sync workstream, not the notion build):**
1. Round at write-time in the sync: `ROUND(value::numeric, 2)` when writing boredom.
2. And/or change the column type to `numeric(3,2)` so storage enforces 2 decimals.
   (Check current type first: `SELECT data_type, numeric_precision, numeric_scale FROM
   information_schema.columns WHERE table_name='brain_subtopic' AND column_name='boredom';`)
3. One-time cleanup of existing rows: `UPDATE brain_subtopic SET boredom = ROUND(boredom::numeric, 2);`
   (and same for brain_interaction if affected).

**Scope check:** affects any brain_* table with a boredom (or other computed float)
column written by the sync. Worth a sweep for similar columns (rates, etc.) while fixing.
