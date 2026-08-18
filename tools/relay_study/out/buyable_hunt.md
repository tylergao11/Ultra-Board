# Buyable-path hunt

Date: 2026-08-17. Historical frequencies only. Not a trading scheme.
Win-rate bar remains 90% on BUYABLE fills. 一字 continuation is discarded, not optimized.

## 1. Price / volume path coverage

Hunted: `data/kaipanla/raw/*/zt_pool.json`, `data/ths/limit_pool`, `data/ths/open_limit_pool`,
`data/ths/stories` (narrative only), `data/research/auction/observations.jsonl` (empty),
`data/research/node_pools` (README only), `site/public/agent-data/v1/days` (pool facts, no OHLC),
parquet/csv/jsonl caches (none outside relay_study/out), kaipanla sentiment/expression/sector_ladder
(market / theme structure, no individual fail-day OHLC).

| path | coverage | usable for fail-day prices? |
| --- | --- | --- |
| kaipanla zt_pool price (close) | 14436/14495 window stocks | only names that sealed that day |
| kaipanla zt_pool open/high/low | 2628 fields, 201/208 days have any | almost only yesterday-seal continuations; 0 fail-day opens |
| THS limit_pool price/change_rate/one_price | 211 days | seal-day only |
| THS open_limit_pool (炸板) price+change_rate | 208 days | YES as t+1 fail print if they touched limit |
| auction observations | 1 bytes | no |
| agent-data days | 207 | no OHLC |
| THS v6 line last3600 (this hunt) | 1108/1109 candidate codes cached |

Candidate rows (boards>=2, 2025-10-09..2026-08-12): **n=2736**.

| t+1 fate | n | price we already had |
| --- | --- | --- |
| in zt_pool | 965 | seal close; open only if enriched (success-only) |
| in 炸板池 (change_rate) | 310 | t+1 close vs t close |
| neither | 1461 | **none** until daily bars |

Daily-bar join (THS last3600, 连板 universe only): t bar 2734/2736, t+1 bar 2723/2736, fail t+1 bar 1759/1771.
Missing t+1 bars listed in `out/missing_next_bars.csv` (n=13).

Unused downloader: `KaipanlaClient.his_daban_list` is not in the backfill contract and was not blasted.
`ultraboard.ths.limit_pool.STOCK_LINE_ENDPOINT` already fetches the same K-line and discards OHLC;
this hunt reuses that endpoint for the 1109-code 连板 universe only, cached under `out/daily_bars/`.

## 2. Entry / win definitions (new; not the old tradable_zt grid)

Entry (t-known): name is in t 涨停池, boards>=2, **not 一字 on t**. That is the only entry set.
Fills:

- `hold_*`: assume a human could have bought during t (non-一字). Mark at t close.
- `open_*`: buy t+1 open **only if t+1 open is not a limit/一字 open**. If 一字 open, no fill (excluded from that denominator).

Wins:

- `zt_3d`: in zt_pool t+1/t+2/t+3 (membership, not a fill)
- `hold_then_zt3`: non-yizi t AND zt_3d (entry at t, membership win)
- `cons_not_lose`: zt_next OR (zha and change_rate>0); absent=loss
- `print_not_lose`: among zt-or-zha prints only: not lose vs t close
- `hold_close`: buy t close, t+1 close > t close (needs bar)
- `hold_not_lose`: buy t close, t+1 close >= t close
- `hold_touch3`: buy t close, any of t+1..t+3 high touches limit
- `open_follow`: buy t+1 open if not yizi-open, t+1 close > open
- `open_follow_flat`: buy t+1 open if not yizi-open, close >= open
- `open_then_zt3`: buy t+1 open if not yizi-open, then zt within 3d
- `touch3`: buy t+1 open if not yizi-open, 3d high touches limit
- `tradable_zt`: next-day tradable zt (old ceiling, baseline only)
- `hold_3d`: buy t close, t+3 close > t close
- `open_3d`: buy t+1 open if not yizi-open, t+3 close > open
- `maxclose3`: buy t close, max(t+1..t+3 close) > t close

`zt_3d` / `hold_then_zt3` are membership, not fills. They are reported, not claimed as 90% buyable.
`print_not_lose` drops the 1461 no-print names — selection bias, diagnostic only.
`tradable_zt` is the old ceiling (~25–37%); not re-mined as a scheme.

Claim bar (buyable fills only): n>=30, full-sample >=90%, both time halves n>=15 and >=90%.
Halves: first 2025-10-09..2026-03-12 / second 2026-03-13..2026-08-12.

## 3. Claimed 90% buyable cells

**None.** No new event × fill-win cell hit 90% on both halves with n>=30.

## 4. Best BUYABLE cells by outcome (n>=30, non-一字 t)

### `open_then_zt3`

| event | n | rate | half1 | half2 |
| --- | --- | --- | --- | --- |
| strong_seal_ge4 | 75 | 48/75 = 64.0% | 32/53 = 60.4% | 16/22 = 72.7% |
| strong_seal_early_ge3 | 141 | 85/141 = 60.3% | 53/92 = 57.6% | 32/49 = 65.3% |
| strong_seal_ge3 | 154 | 92/154 = 59.7% | 59/102 = 57.8% | 33/52 = 63.5% |
| intact_strong_ge3 | 96 | 57/96 = 59.4% | 35/61 = 57.4% | 22/35 = 62.9% |
| early_ge5 | 107 | 61/107 = 57.0% | 34/62 = 54.8% | 27/45 = 60.0% |
| non_yizi_5p | 127 | 70/127 = 55.1% | 43/80 = 53.8% | 27/47 = 57.4% |
| early_ge4 | 251 | 135/251 = 53.8% | 78/150 = 52.0% | 57/101 = 56.4% |
| circ_mid_ge3 | 500 | 257/500 = 51.4% | 143/284 = 50.4% | 114/216 = 52.8% |

### `touch3`

| event | n | rate | half1 | half2 |
| --- | --- | --- | --- | --- |
| strong_seal_ge4 | 75 | 53/75 = 70.7% | 36/53 = 67.9% | 17/22 = 77.3% |
| intact_strong_ge3 | 96 | 67/96 = 69.8% | 41/61 = 67.2% | 26/35 = 74.3% |
| strong_seal_ge3 | 154 | 106/154 = 68.8% | 68/102 = 66.7% | 38/52 = 73.1% |
| strong_seal_early_ge3 | 141 | 97/141 = 68.8% | 61/92 = 66.3% | 36/49 = 73.5% |
| early_ge4 | 251 | 162/251 = 64.5% | 93/150 = 62.0% | 69/101 = 68.3% |
| early_ge5 | 107 | 69/107 = 64.5% | 36/62 = 58.1% | 33/45 = 73.3% |
| intact_new_high | 97 | 62/97 = 63.9% | 26/41 = 63.4% | 36/56 = 64.3% |
| circ_mid_ge3 | 500 | 315/500 = 63.0% | 175/284 = 61.6% | 140/216 = 64.8% |

### `open_follow`

| event | n | rate | half1 | half2 |
| --- | --- | --- | --- | --- |
| intact_sub_high | 62 | 36/62 = 58.1% | 16/26 = 61.5% | 20/36 = 55.6% |
| opened_today_mid23 | 1261 | 629/1261 = 49.9% | 305/638 = 47.8% | 324/623 = 52.0% |
| break_new_high_non_yizi | 117 | 58/117 = 49.6% | 21/43 = 48.8% | 37/74 = 50.0% |
| non_yizi_new_high | 214 | 103/214 = 48.1% | 39/84 = 46.4% | 64/130 = 49.2% |
| intact_mid23 | 1067 | 512/1067 = 48.0% | 266/535 = 49.7% | 246/532 = 46.2% |
| break_theme_alive_mid23 | 461 | 221/461 = 47.9% | 66/153 = 43.1% | 155/308 = 50.3% |
| drop_same_theme_mid23 | 48 | 23/48 = 47.9% | 8/15 = 53.3% | 15/33 = 45.5% |
| intact_theme_alive_mid23 | 885 | 423/885 = 47.8% | 214/441 = 48.5% | 209/444 = 47.1% |

### `open_follow_flat`

| event | n | rate | half1 | half2 |
| --- | --- | --- | --- | --- |
| intact_sub_high | 62 | 38/62 = 61.3% | 16/26 = 61.5% | 22/36 = 61.1% |
| early_ge5 | 107 | 65/107 = 60.7% | 37/62 = 59.7% | 28/45 = 62.2% |
| non_yizi_5p | 127 | 77/127 = 60.6% | 47/80 = 58.8% | 30/47 = 63.8% |
| break_new_high_non_yizi | 117 | 69/117 = 59.0% | 25/43 = 58.1% | 44/74 = 59.5% |
| early_ge4 | 251 | 147/251 = 58.6% | 84/150 = 56.0% | 63/101 = 62.4% |
| theme8_ge3 | 200 | 117/200 = 58.5% | 63/105 = 60.0% | 54/95 = 56.8% |
| non_yizi_new_high | 214 | 124/214 = 57.9% | 48/84 = 57.1% | 76/130 = 58.5% |
| non_yizi_4 | 173 | 99/173 = 57.2% | 56/102 = 54.9% | 43/71 = 60.6% |

### `hold_close`

| event | n | rate | half1 | half2 |
| --- | --- | --- | --- | --- |
| theme8_ge3 | 212 | 142/212 = 67.0% | 70/112 = 62.5% | 72/100 = 72.0% |
| theme8_3 | 115 | 77/115 = 67.0% | 36/56 = 64.3% | 41/59 = 69.5% |
| strong_seal_ge4 | 81 | 54/81 = 66.7% | 38/56 = 67.9% | 16/25 = 64.0% |
| strong_seal_early_ge3 | 150 | 94/150 = 62.7% | 59/97 = 60.8% | 35/53 = 66.0% |
| intact_strong_ge3 | 99 | 62/99 = 62.6% | 39/63 = 61.9% | 23/36 = 63.9% |
| strong_seal_ge3 | 163 | 102/163 = 62.6% | 65/107 = 60.7% | 37/56 = 66.1% |
| theme10_any | 579 | 361/579 = 62.3% | 165/286 = 57.7% | 196/293 = 66.9% |
| theme8_mid23 | 644 | 389/644 = 60.4% | 169/299 = 56.5% | 220/345 = 63.8% |

### `hold_not_lose`

| event | n | rate | half1 | half2 |
| --- | --- | --- | --- | --- |
| strong_seal_ge4 | 81 | 55/81 = 67.9% | 39/56 = 69.6% | 16/25 = 64.0% |
| theme8_ge3 | 212 | 142/212 = 67.0% | 70/112 = 62.5% | 72/100 = 72.0% |
| theme8_3 | 115 | 77/115 = 67.0% | 36/56 = 64.3% | 41/59 = 69.5% |
| intact_strong_ge3 | 99 | 63/99 = 63.6% | 40/63 = 63.5% | 23/36 = 63.9% |
| theme10_any | 579 | 368/579 = 63.6% | 168/286 = 58.7% | 200/293 = 68.3% |
| strong_seal_early_ge3 | 150 | 95/150 = 63.3% | 60/97 = 61.9% | 35/53 = 66.0% |
| strong_seal_ge3 | 163 | 103/163 = 63.2% | 66/107 = 61.7% | 37/56 = 66.1% |
| theme8_mid23 | 644 | 397/644 = 61.6% | 172/299 = 57.5% | 225/345 = 65.2% |

### `hold_touch3`

| event | n | rate | half1 | half2 |
| --- | --- | --- | --- | --- |
| strong_seal_ge4 | 81 | 59/81 = 72.8% | 39/56 = 69.6% | 20/25 = 80.0% |
| intact_strong_ge3 | 99 | 70/99 = 70.7% | 43/63 = 68.3% | 27/36 = 75.0% |
| strong_seal_early_ge3 | 150 | 106/150 = 70.7% | 66/97 = 68.0% | 40/53 = 75.5% |
| strong_seal_ge3 | 163 | 115/163 = 70.6% | 73/107 = 68.2% | 42/56 = 75.0% |
| early_ge4 | 262 | 172/262 = 65.6% | 99/157 = 63.1% | 73/105 = 69.5% |
| early_ge5 | 112 | 73/112 = 65.2% | 39/66 = 59.1% | 34/46 = 73.9% |
| intact_new_high | 100 | 65/100 = 65.0% | 28/43 = 65.1% | 37/57 = 64.9% |
| circ_mid_ge3 | 522 | 334/522 = 64.0% | 189/301 = 62.8% | 145/221 = 65.6% |

### `cons_not_lose`

| event | n | rate | half1 | half2 |
| --- | --- | --- | --- | --- |
| strong_seal_ge4 | 81 | 49/81 = 60.5% | 33/56 = 58.9% | 16/25 = 64.0% |
| strong_seal_early_ge3 | 150 | 87/150 = 58.0% | 54/97 = 55.7% | 33/53 = 62.3% |
| strong_seal_ge3 | 163 | 94/163 = 57.7% | 60/107 = 56.1% | 34/56 = 60.7% |
| intact_strong_ge3 | 99 | 57/99 = 57.6% | 36/63 = 57.1% | 21/36 = 58.3% |
| early_ge5 | 113 | 57/113 = 50.4% | 33/67 = 49.3% | 24/46 = 52.2% |
| strong_seal_ny | 392 | 196/392 = 50.0% | 132/265 = 49.8% | 64/127 = 50.4% |
| theme8_ge3 | 213 | 106/213 = 49.8% | 57/113 = 50.4% | 49/100 = 49.0% |
| non_yizi_5p | 135 | 66/135 = 48.9% | 41/87 = 47.1% | 25/48 = 52.1% |

### `hold_3d`

| event | n | rate | half1 | half2 |
| --- | --- | --- | --- | --- |
| intact_strong_ge3 | 95 | 53/95 = 55.8% | 33/63 = 52.4% | 20/32 = 62.5% |
| non_yizi_5p | 128 | 71/128 = 55.5% | 44/83 = 53.0% | 27/45 = 60.0% |
| early_ge5 | 107 | 59/107 = 55.1% | 33/64 = 51.6% | 26/43 = 60.5% |
| theme8_ge3 | 205 | 112/205 = 54.6% | 52/109 = 47.7% | 60/96 = 62.5% |
| strong_seal_ge4 | 79 | 43/79 = 54.4% | 27/55 = 49.1% | 16/24 = 66.7% |
| strong_seal_early_ge3 | 145 | 77/145 = 53.1% | 48/96 = 50.0% | 29/49 = 59.2% |
| intact_new_high | 97 | 51/97 = 52.6% | 22/42 = 52.4% | 29/55 = 52.7% |
| suc80_ge3 | 333 | 174/333 = 52.3% | 97/193 = 50.3% | 77/140 = 55.0% |

### `open_3d`

| event | n | rate | half1 | half2 |
| --- | --- | --- | --- | --- |
| drop_theme_alive_mid23 | 302 | 154/302 = 51.0% | 52/111 = 46.8% | 102/191 = 53.4% |
| break_new_high_non_yizi | 116 | 59/116 = 50.9% | 23/43 = 53.5% | 36/73 = 49.3% |
| break_theme_alive_mid23 | 460 | 226/460 = 49.1% | 75/153 = 49.0% | 151/307 = 49.2% |
| drop_mid23 | 487 | 238/487 = 48.9% | 100/220 = 45.5% | 138/267 = 51.7% |
| break_opened_mid23 | 518 | 248/518 = 47.9% | 107/252 = 42.5% | 141/266 = 53.0% |
| non_yizi_new_high | 210 | 99/210 = 47.1% | 42/83 = 50.6% | 57/127 = 44.9% |
| intact_sub_high | 62 | 29/62 = 46.8% | 10/26 = 38.5% | 19/36 = 52.8% |
| opened_today_mid23 | 1243 | 581/1243 = 46.7% | 269/634 = 42.4% | 312/609 = 51.2% |

### `maxclose3`

| event | n | rate | half1 | half2 |
| --- | --- | --- | --- | --- |
| theme8_3 | 115 | 90/115 = 78.3% | 40/56 = 71.4% | 50/59 = 84.7% |
| theme8_ge3 | 212 | 162/212 = 76.4% | 78/112 = 69.6% | 84/100 = 84.0% |
| theme10_any | 579 | 423/579 = 73.1% | 191/286 = 66.8% | 232/293 = 79.2% |
| strong_seal_ge4 | 81 | 59/81 = 72.8% | 40/56 = 71.4% | 19/25 = 76.0% |
| theme8_mid23 | 644 | 464/644 = 72.0% | 199/299 = 66.6% | 265/345 = 76.8% |
| strong_seal_early_ge3 | 150 | 106/150 = 70.7% | 65/97 = 67.0% | 41/53 = 77.4% |
| strong_seal_ge3 | 163 | 114/163 = 69.9% | 71/107 = 66.4% | 43/56 = 76.8% |
| break_new_high_non_yizi | 123 | 86/123 = 69.9% | 28/44 = 63.6% | 58/79 = 73.4% |

## 5. 3-day membership (not a fill) — new target

Selected at t, non-一字, outcome = in zt_pool on t+1 or t+2 or t+3.

| event | n | zt_3d | half1 | half2 |
| --- | --- | --- | --- | --- |
| ALL_non_yizi_t | 2225 | 915/2225 = 41.1% | 494/1139 = 43.4% | 421/1086 = 38.8% |
| non_yizi_2 | 1526 | 562/1526 = 36.8% | 291/739 = 39.4% | 271/787 = 34.4% |
| non_yizi_3 | 385 | 187/385 = 48.6% | 101/208 = 48.6% | 86/177 = 48.6% |
| non_yizi_4 | 179 | 90/179 = 50.3% | 54/105 = 51.4% | 36/74 = 48.6% |
| non_yizi_5p | 135 | 76/135 = 56.3% | 48/87 = 55.2% | 28/48 = 58.3% |
| non_yizi_mid23 | 1911 | 749/1911 = 39.2% | 392/947 = 41.4% | 357/964 = 37.0% |
| non_yizi_sub_high | 347 | 117/347 = 33.7% | 46/142 = 32.4% | 71/205 = 34.6% |
| non_yizi_new_high | 225 | 114/225 = 50.7% | 41/89 = 46.1% | 73/136 = 53.7% |
| break_all_non_yizi | 906 | 367/906 = 40.5% | 186/450 = 41.3% | 181/456 = 39.7% |
| break_same_theme_non_yizi | 86 | 32/86 = 37.2% | 14/33 = 42.4% | 18/53 = 34.0% |
| break_same_theme_mid23 | 79 | 29/79 = 36.7% | 11/27 = 40.7% | 18/52 = 34.6% |
| break_same_theme_2 | 66 | 22/66 = 33.3% | 9/24 = 37.5% | 13/42 = 31.0% |
| break_mid23 | 806 | 314/806 = 39.0% | 150/384 = 39.1% | 164/422 = 38.9% |
| break_new_high_non_yizi | 123 | 64/123 = 52.0% | 21/44 = 47.7% | 43/79 = 54.4% |
| break_theme_alive_mid23 | 476 | 181/476 = 38.0% | 61/159 = 38.4% | 120/317 = 37.9% |
| break_theme_alive_same_mid23 | 76 | 26/76 = 34.2% | 8/24 = 33.3% | 18/52 = 34.6% |
| intact_mid23 | 1105 | 435/1105 = 39.4% | 242/563 = 43.0% | 193/542 = 35.6% |
| intact_sub_high | 64 | 29/64 = 45.3% | 12/28 = 42.9% | 17/36 = 47.2% |
| intact_new_high | 102 | 50/102 = 49.0% | 20/45 = 44.4% | 30/57 = 52.6% |
| drop_mid23 | 509 | 213/509 = 41.8% | 98/232 = 42.2% | 115/277 = 41.5% |
| drop_same_theme_mid23 | 51 | 18/51 = 35.3% | 5/15 = 33.3% | 13/36 = 36.1% |
| drop_theme_alive_mid23 | 315 | 127/315 = 40.3% | 47/117 = 40.2% | 80/198 = 40.4% |
| intact_theme_alive_mid23 | 917 | 363/917 = 39.6% | 195/466 = 41.8% | 168/451 = 37.3% |
| theme_n_ge3_mid23 | 1321 | 524/1321 = 39.7% | 263/646 = 40.7% | 261/675 = 38.7% |
| theme_n_ge4_mid23 | 1129 | 448/1129 = 39.7% | 213/535 = 39.8% | 235/594 = 39.6% |
| theme_n_ge5_2 | 802 | 299/802 = 37.3% | 149/376 = 39.6% | 150/426 = 35.2% |
| opened_today_mid23 | 1293 | 505/1293 = 39.1% | 270/660 = 40.9% | 235/633 = 37.1% |
| unopened_non_yizi_mid23 | 618 | 244/618 = 39.5% | 122/287 = 42.5% | 122/331 = 36.9% |
| break_opened_mid23 | 533 | 207/533 = 38.8% | 95/261 = 36.4% | 112/272 = 41.2% |
| amt_mid_mid23 | 367 | 158/367 = 43.1% | 77/145 = 53.1% | 81/222 = 36.5% |
| strong_seal_ny | 392 | 215/392 = 54.8% | 145/265 = 54.7% | 70/127 = 55.1% |
| strong_seal_ge3 | 163 | 101/163 = 62.0% | 64/107 = 59.8% | 37/56 = 66.1% |
| strong_seal_ge4 | 81 | 54/81 = 66.7% | 35/56 = 62.5% | 19/25 = 76.0% |
| early_ge4 | 263 | 146/263 = 55.5% | 85/158 = 53.8% | 61/105 = 58.1% |
| early_ge5 | 113 | 66/113 = 58.4% | 38/67 = 56.7% | 28/46 = 60.9% |
| early_3 | 306 | 153/306 = 50.0% | 88/173 = 50.9% | 65/133 = 48.9% |
| strong_seal_early_ge3 | 150 | 94/150 = 62.7% | 58/97 = 59.8% | 36/53 = 67.9% |
| theme8_mid23 | 644 | 247/644 = 38.4% | 111/299 = 37.1% | 136/345 = 39.4% |
| theme8_ge3 | 213 | 108/213 = 50.7% | 56/113 = 49.6% | 52/100 = 52.0% |
| theme8_3 | 115 | 54/115 = 47.0% | 25/56 = 44.6% | 29/59 = 49.2% |
| theme10_any | 580 | 236/580 = 40.7% | 117/287 = 40.8% | 119/293 = 40.6% |
| suc80_ge3 | 339 | 173/339 = 51.0% | 100/197 = 50.8% | 73/142 = 51.4% |
| intact_strong_ge3 | 99 | 60/99 = 60.6% | 37/63 = 58.7% | 23/36 = 63.9% |
| circ_mid_ge3 | 523 | 279/523 = 53.3% | 160/302 = 53.0% | 119/221 = 53.8% |

## 6. Theme persistence (theme-day, not a stock fill)

Selection uses t theme counts only. Win = that theme still has enough 涨停 on t+1.

| rule | n | rate | half1 | half2 |
| --- | --- | --- | --- | --- |
| theme_n>=2 and next>=1 | 2478 | 1577/2478 = 63.6% | 726/1188 = 61.1% | 851/1290 = 66.0% |
| theme_n>=3 and next>=1 | 1511 | 1101/1511 = 72.9% | 518/721 = 71.8% | 583/790 = 73.8% |
| theme_n>=3 and next>=2 | 1511 | 881/1511 = 58.3% | 412/721 = 57.1% | 469/790 = 59.4% |
| theme_n>=4 and next>=1 | 1051 | 826/1051 = 78.6% | 372/483 = 77.0% | 454/568 = 79.9% |
| theme_n>=4 and next>=2 | 1051 | 686/1051 = 65.3% | 307/483 = 63.6% | 379/568 = 66.7% |
| theme_n>=5 and next>=1 | 789 | 647/789 = 82.0% | 289/363 = 79.6% | 358/426 = 84.0% |
| theme_n>=5 and next>=2 | 789 | 559/789 = 70.8% | 251/363 = 69.1% | 308/426 = 72.3% |
| theme_n>=5 and next>=3 | 789 | 458/789 = 58.0% | 195/363 = 53.7% | 263/426 = 61.7% |
| theme_n>=6 and next>=1 | 591 | 502/591 = 84.9% | 218/265 = 82.3% | 284/326 = 87.1% |
| theme_n>=8 and next>=1 | 381 | 346/381 = 90.8% | 150/166 = 90.4% | 196/215 = 91.2% |
| theme_n>=8 and next>=2 | 381 | 318/381 = 83.5% | 137/166 = 82.5% | 181/215 = 84.2% |
| theme_n>=10 and next>=1 | 258 | 244/258 = 94.6% | 108/115 = 93.9% | 136/143 = 95.1% |
| theme_n>=10 and next>=2 | 258 | 226/258 = 87.6% | 98/115 = 85.2% | 128/143 = 89.5% |
| theme_n>=12 and next>=1 | 190 | 182/190 = 95.8% | 79/82 = 96.3% | 103/108 = 95.4% |
| theme_n>=15 and next>=1 | 129 | 126/129 = 97.7% | 54/55 = 98.2% | 72/74 = 97.3% |

## 7. Grid on the new price outcomes (not the old tradable_zt grid)

`grid_buyable.py`: 1160 event x outcome cells over non-一字 t. **claim90 = 0**.

Closest n>=30 buyable-fill cells (both halves shown; none reach 90%):

| outcome | filters | n | rate | half1 | half2 |
| --- | --- | --- | --- | --- | --- |
| maxclose3 | boards>=4 & seal_ratio>=2% & theme_n>=5 | 46 | 38/46 = 82.6% | 23/28 = 82.1% | 15/18 = 83.3% |
| hold_touch3 | boards>=4 & seal_ratio>=2% & theme_n>=5 | 46 | 36/46 = 78.3% | 22/28 = 78.6% | 14/18 = 77.8% |
| hold_close | boards>=4 & seal_ratio>=2% & theme_n>=5 | 46 | 36/46 = 78.3% | 23/28 = 82.1% | 13/18 = 72.2% |
| touch3 | boards>=4 & seal_ratio>=2% & theme_n>=5 | 41 | 31/41 = 75.6% | 20/26 = 76.9% | 11/15 = 73.3% |
| hold_close | theme_n>=8 & boards>=3 | 212 | 142/212 = 67.0% | 70/112 = 62.5% | 72/100 = 72.0% |
| touch3 | strong_seal & boards>=4 | 75 | 53/75 = 70.7% | 36/53 = 67.9% | 17/22 = 77.3% |

`maxclose3` is the mildest win (any of the next 3 closes beats t close). Even that tops out at **82.6%** with n=46, not 90%.
Smaller n=20-22 slices reach ~80-82% (`ge5 & strong & theme_n>=5`) but fail the n/half gates.

Full grid: `out/buyable_grid.csv`.

## 8. Verdict

**No buyable rule hit >=90% with n>=30 and both time halves >=90%.**

This is after:
- hunting every local price path (zt_pool OHLC is success-only; 炸板 gives 310 fail closes; auction empty);
- fetching THS last3600 daily bars for 1108/1109 连板 codes (the unused OHLC inside `limit_pool.STOCK_LINE_ENDPOINT`);
- new events that were not the old tradable_zt grid: 断板后同题材 2/3 板, 未断时中位梯队, 3-day 再封 membership, 3-day high-touch, t+1 open follow, hold-from-t-close, seal/early/theme-n slices.

Best honest BUYABLE cell: **non-一字, boards>=4, seal_order_ratio>=2%, own theme has >=5 涨停 that day**, buy at t close, win = max(t+1..t+3 close) > t close → **82.6% (38/46)**, halves 82.1% / 83.3%. Not a scheme.

Theme persistence `theme_n>=8 and next>=1` is 90.8% (381 theme-days, both halves >=90%). That is **not a stock fill** — it only says a crowded theme still has someone at limit tomorrow. Picking a specific non-一字 name from those themes does not inherit the 90%.

Old `tradable_zt` ceiling (~25-37%) was not re-mined.

## 9. What is missing to continue

Specific holes, not a request for another 一字 memo:

- **竞价**: `data/research/auction/observations.jsonl` is empty. No indicative price / matched amount. Cannot test 次日开盘可排板 as a t-known or t+1 09:20 fill.
- **分时 / 开板价 / 炸板价**: none on disk. 回封打板 still cannot be filled.
- **Halt gaps**: 13 candidate t+1 bars missing. 12 are fail-day with no THS bar (typical halt / no-trade). `603056` 德邦股份 last3600 returns `total=0` (year 2025/2026 404). Not an API skip — the source has no line.
- **`his_daban_list`**: exists on `KaipanlaClient`, not in the backfill contract, not fetched. Unknown whether it has fail-day opens. Do not blast it without a one-day contract test.
- **Full-market daily bars** beyond the 1109-code 连板 universe: not needed for this candidate set (99.5% t+1 join). Would only matter for names that were never 连板.
- To push a stock-level buyable win toward 90% with n>=30 both halves, the missing pieces are **intraday / auction prints**, not another boolean combo on these fields. The price-path grid already sits at 75-83% on the tightest honest slices.

Files: `out/buyable_cells.csv`, `out/buyable_grid.csv`, `out/missing_next_bars.csv`, `out/theme_persist.csv`, `out/daily_bars/`, `out/daily_bars_fetch_log.json`.
Scripts: `fetch_daily_bars.py`, `hunt_buyable.py`, `grid_buyable.py`.
Re-run hunter: `python tools/relay_study/hunt_buyable.py`
Re-run grid: `python tools/relay_study/grid_buyable.py`
