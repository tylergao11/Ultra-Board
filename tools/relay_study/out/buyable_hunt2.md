# Buyable-path hunt 2

Date: 2026-08-17. Historical frequencies only. Not a trading scheme.
Win-rate bar remains 90% on BUYABLE fills. Yi-zi continuation is discarded, not optimized.
Halves: first 2025-10-09..2026-03-12 / second 2026-03-13..2026-08-12 (mid_date=2026-03-13).

## 0. CLAIMED 90% buyable stock rules

Two name-pick rules hit n>=30, full-sample >=90%, both halves n>=15 and >=90%.
Win is maxc3 (buy t close, max of next 3 closes > buy). Next-day hold_close is about 78%, not 90%.
Filter-then-pick equals pick-then-veto on both cells (same members).
All members re-read from out/daily_bars/{code}.json; stored maxc3 matches raw OHLC 42/42 and 46/46.
No t-day yi-zi OHLC in either set. Selector uses t-known fields only.

### Rule A -- 3-board strongest seal on intact crowded-theme days

- Universe (t-known): not yi-zi, boards==3, own theme_n>=8, market intact (not height_drop) and leader still present (not leader_absent).
- Selector: 1 name per day = max seal_order_ratio, tie-break code.
- Buy: t close (THS limit_pool price, else bar close).
- Win: max(t+1, t+2, t+3 close) > buy.
- **39/42 = 92.9%**. half1 21/23 = 91.3%. half2 18/19 = 94.7%.
- Losses (3): 2026-01-12 603017 Zhongheng Design; 2026-02-11 603980 Jihua; 2026-06-16 301176 Yihao.

- maxc3: 39/42 = 92.9% | h1 21/23 = 91.3% | h2 18/19 = 94.7% CLAIM
- hold_close: 33/42 = 78.6% | h1 18/23 = 78.3% | h2 15/19 = 78.9%
- hold_flat: 33/42 = 78.6% | h1 18/23 = 78.3% | h2 15/19 = 78.9%
- hold_touch3: 30/42 = 71.4% | h1 18/23 = 78.3% | h2 12/19 = 63.2%
- hold_3d: 22/41 = 53.7% | h1 12/23 = 52.2% | h2 10/18 = 55.6%
- open_up: 22/41 = 53.7% | h1 12/22 = 54.5% | h2 10/19 = 52.6%
- open_flat: 27/41 = 65.9% | h1 15/22 = 68.2% | h2 12/19 = 63.2%
- touch3: 30/41 = 73.2% | h1 18/22 = 81.8% | h2 12/19 = 63.2%
- hold_zt3: 22/42 = 52.4% | h1 12/23 = 52.2% | h2 10/19 = 52.6%

| date | code | name | theme | H | tn | seal | oc | type | px_t | c1 | c2 | c3 | maxc3 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-10-20 | 603933 | 睿能科技 | 芯片 | 5 | 8 | 0.013 | 2 | T字板 | 21.98 | 21.24 | 23.37 | 21.03 | True |
| 2025-10-22 | 600172 | 黄河旋风 | 国有企业 | 7 | 11 | 0.020 | 1 | 换手板 | 7.72 | 7.73 | 6.96 | 7.01 | True |
| 2025-11-04 | 000592 | 平潭发展 | 福建 | 6 | 17 | 0.017 | 4 | 换手板 | 8.57 | 9.43 | 8.49 | 8.9 | True |
| 2025-11-05 | 002885 | 京泉华 | 智能电网 | 7 | 19 | 0.013 | 1 | 换手板 | 32.25 | 33.93 | 35.93 | 33.62 | True |
| 2025-11-17 | 001203 | 大中矿业 | 锂电池 | 8 | 14 | 0.003 | 4 | 换手板 | 30.89 | 30.62 | 32.09 | 34.37 | True |
| 2025-11-24 | 600734 | 实达集团 | 人工智能 | 7 | 15 | 0.018 | 6 | T字板 | 5.08 | 5.59 | 6.15 | 5.54 | True |
| 2025-12-08 | 605299 | 舒华体育 | 海峡两岸 | 5 | 18 | 0.010 | 0 | 换手板 | 14.25 | 15.48 | 15.0 | 13.48 | True |
| 2025-12-09 | 000905 | 厦门港务 | 海峡两岸 | 6 | 11 | 0.011 | 3 | 换手板 | 14.52 | 15.9 | 15.13 | 13.81 | True |
| 2025-12-24 | 002228 | 合兴包装 | 海峡两岸 | 9 | 10 | 0.014 | 1 | 换手板 | 5.95 | 6.39 | 6.17 | 5.54 | True |
| 2025-12-26 | 603278 | 大业股份 | 商业航天 | 11 | 20 | 0.019 | 2 | T字板 | 12.8 | 14.08 | 15.49 | 17.04 | True |
| 2025-12-29 | 002347 | 泰尔股份 | 机器人概念 | 12 | 11 | 0.014 | 9 | 换手板 | 10.23 | 11.25 | 12.38 | 13.14 | True |
| 2026-01-05 | 002757 | 南兴股份 | 人工智能 | 7 | 10 | 0.020 | 2 | 换手板 | 21.42 | 23.36 | 21.41 | 23.57 | True |
| 2026-01-06 | 002151 | 北斗星通 | 商业航天 | 13 | 15 | 0.014 | 1 | 换手板 | 54.97 | 57.7 | 59.69 | 60.82 | True |
| 2026-01-09 | 600637 | 东方明珠 | 人工智能 | 11 | 30 | 0.007 | 5 | T字板 | 13.32 | 14.52 | 15.26 | 14.73 | True |
| 2026-01-12 | 603017 | 中衡设计 | 商业航天 | 12 | 43 | 0.019 | 0 | 换手板 | 14.63 | 13.02 | 12.26 | 11.91 | False |
| 2026-01-13 | 603598 | 引力传媒 | 人工智能 | 13 | 31 | 0.016 | 2 | T字板 | 31.37 | 32.4 | 31.51 | 28.36 | True |
| 2026-01-23 | 002342 | 巨力索具 | 商业航天 | 18 | 17 | 0.021 | 0 | 换手板 | 13.54 | 13.7 | 13.2 | 14.52 | True |
| 2026-01-27 | 002218 | 拓日新能 | 光伏 | 6 | 8 | 0.019 | 2 | 换手板 | 6.61 | 6.9 | 6.56 | 5.9 | True |
| 2026-01-28 | 000506 | 招金黄金 | 黄金 | 7 | 29 | 0.010 | 1 | 换手板 | 25.93 | 28.52 | 25.67 | 23.1 | True |
| 2026-02-11 | 603980 | 吉华集团 | 化工 | 4 | 16 | 0.004 | 10 | 换手板 | 8.72 | 8.49 | 7.63 | 8.11 | False |
| 2026-02-27 | 002378 | 章源钨业 | 有色金属 | 7 | 15 | 0.005 | 0 | 换手板 | 40.6 | 43.82 | 41.51 | 44.86 | True |
| 2026-03-06 | 002498 | 汉缆股份 | 智能电网 | 3 | 9 | 0.006 | 5 | 换手板 | 9.83 | 9.92 | 9.61 | 9.4 | True |
| 2026-03-09 | 000815 | 美利云 | 算力 | 4 | 9 | 0.011 | 2 | 换手板 | 17.94 | 17.9 | 17.73 | 18.84 | True |
| 2026-03-13 | 600722 | 金牛化工 | 化工 | 5 | 9 | 0.002 | 18 | 换手板 | 16.94 | 18.4 | 19.3 | 17.37 | True |
| 2026-03-25 | 600758 | 辽宁能源 | 电力 | 8 | 15 | 0.021 | 3 | T字板 | 5.72 | 6.14 | 5.53 | 4.98 | True |
| 2026-04-07 | 000720 | 新能泰山 | 通信 | 7 | 12 | 0.027 | 0 | 换手板 | 6.53 | 6.7 | 6.03 | 5.43 | True |
| 2026-04-13 | 002580 | 圣阳股份 | 算力 | 5 | 9 | 0.022 | 2 | 换手板 | 20.88 | 22.93 | 25.23 | 27.76 | True |
| 2026-04-16 | 002990 | 盛视科技 | 算力 | 6 | 20 | 0.007 | 16 | 换手板 | 46.32 | 50.85 | 48.9 | 45.05 | True |
| 2026-04-30 | 600379 | 宝光股份 | 芯片 | 4 | 12 | 0.028 | 0 | 换手板 | 16.78 | 18.43 | 17.82 | 16.72 | True |
| 2026-05-11 | 002491 | 通鼎互联 | 通信 | 5 | 16 | 0.008 | 4 | T字板 | 22.73 | 25.0 | 26.95 | 24.65 | True |
| 2026-05-13 | 600396 | 华电辽能 | 电力 | 6 | 17 | 0.007 | 1 | 换手板 | 16.56 | 16.64 | 17.43 | 15.69 | True |
| 2026-05-20 | 000417 | 合百集团 | 芯片 | 8 | 26 | 0.038 | 0 | 换手板 | 9.53 | 9.25 | 10.18 | 10.29 | True |
| 2026-05-28 | 002579 | 中京电子 | 通信 | 4 | 17 | 0.016 | 0 | 换手板 | 18.19 | 17.15 | 18.87 | 20.76 | True |
| 2026-05-29 | 000539 | 粤电力Ａ | 电力 | 5 | 8 | 0.008 | 1 | 换手板 | 8.88 | 9.75 | 9.11 | 9.38 | True |
| 2026-06-05 | 603135 | 中重科技 | 机器人概念 | 5 | 14 | 0.007 | 0 | 换手板 | 14.03 | 15.43 | 15.8 | 14.22 | True |
| 2026-06-10 | 002636 | 金安国纪 | 通信 | 4 | 8 | 0.003 | 16 | 换手板 | 77.42 | 84.8 | 89.88 | 97.34 | True |
| 2026-06-16 | 301176 | 逸豪新材 | 通信 | 4 | 25 | 0.000 | 5 | 换手板 | 81.5 | 79.89 | 78.64 | 77.48 | False |
| 2026-06-18 | 002141 | 贤丰控股 | 通信 | 4 | 11 | 0.023 | 0 | 换手板 | 4.71 | 4.5 | 4.95 | 4.76 | True |
| 2026-07-09 | 002841 | 视源股份 | 中报增长 | 8 | 9 | 0.000 | 135 | 换手板 | 52.13 | 52.45 | 50.92 | 51.6 | True |
| 2026-07-23 | 002879 | 长缆科技 | 智能电网 | 6 | 27 | 0.064 | 2 | 换手板 | 16.41 | 18.05 | 19.86 | 18.9 | True |
| 2026-08-04 | 000815 | 美利云 | 算力 | 7 | 27 | 0.023 | 0 | 换手板 | 18.37 | 18.85 | 18.31 | 18.03 | True |
| 2026-08-11 | 600664 | 哈药股份 | 医药 | 6 | 8 | 0.006 | 20 | 换手板 | 8.27 | 8.81 | 8.86 | None | True |

### Rule B -- 3-board strongest seal, not the day high, theme_n>=10

- Universe (t-known): not yi-zi, boards==3, own theme_n>=10, boards < H (not the day high).
- Selector: 1 name per day = max seal_order_ratio, tie-break code.
- Buy / win: same as A (t close / maxc3).
- **42/46 = 91.3%**. half1 23/25 = 92.0%. half2 19/21 = 90.5%.
- Losses (4): A's three plus 2026-07-03 605189 Fuchun.
- Overlap with A: 32 names.

- maxc3: 42/46 = 91.3% | h1 23/25 = 92.0% | h2 19/21 = 90.5% CLAIM
- hold_close: 36/46 = 78.3% | h1 21/25 = 84.0% | h2 15/21 = 71.4%
- hold_flat: 36/46 = 78.3% | h1 21/25 = 84.0% | h2 15/21 = 71.4%
- hold_touch3: 34/46 = 73.9% | h1 19/25 = 76.0% | h2 15/21 = 71.4%
- hold_3d: 25/46 = 54.3% | h1 14/25 = 56.0% | h2 11/21 = 52.4%
- open_up: 20/44 = 45.5% | h1 12/23 = 52.2% | h2 8/21 = 38.1%
- open_flat: 25/44 = 56.8% | h1 16/23 = 69.6% | h2 9/21 = 42.9%
- touch3: 33/44 = 75.0% | h1 18/23 = 78.3% | h2 15/21 = 71.4%
- hold_zt3: 27/46 = 58.7% | h1 16/25 = 64.0% | h2 11/21 = 52.4%

| date | code | name | theme | H | tn | seal | oc | type | px_t | c1 | c2 | c3 | maxc3 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-10-22 | 600172 | 黄河旋风 | 国有企业 | 7 | 11 | 0.020 | 1 | 换手板 | 7.72 | 7.73 | 6.96 | 7.01 | True |
| 2025-11-04 | 000592 | 平潭发展 | 福建 | 6 | 17 | 0.017 | 4 | 换手板 | 8.57 | 9.43 | 8.49 | 8.9 | True |
| 2025-11-05 | 002885 | 京泉华 | 智能电网 | 7 | 19 | 0.013 | 1 | 换手板 | 32.25 | 33.93 | 35.93 | 33.62 | True |
| 2025-11-14 | 603026 | 石大胜华 | 锂电池 | 7 | 10 | 0.009 | 0 | 换手板 | 100.52 | 106.75 | 96.07 | 90.31 | True |
| 2025-11-17 | 001203 | 大中矿业 | 锂电池 | 8 | 14 | 0.003 | 4 | 换手板 | 30.89 | 30.62 | 32.09 | 34.37 | True |
| 2025-11-24 | 600734 | 实达集团 | 人工智能 | 7 | 15 | 0.018 | 6 | T字板 | 5.08 | 5.59 | 6.15 | 5.54 | True |
| 2025-11-25 | 000892 | 欢瑞世纪 | 人工智能 | 5 | 10 | 0.018 | 0 | 换手板 | 8.86 | 9.75 | 8.78 | 8.04 | True |
| 2025-12-05 | 600151 | 航天机电 | 商业航天 | 4 | 13 | 0.005 | 3 | 换手板 | 13.65 | 13.48 | 14.83 | 14.28 | True |
| 2025-12-08 | 605299 | 舒华体育 | 海峡两岸 | 5 | 18 | 0.010 | 0 | 换手板 | 14.25 | 15.48 | 15.0 | 13.48 | True |
| 2025-12-09 | 000905 | 厦门港务 | 海峡两岸 | 6 | 11 | 0.011 | 3 | 换手板 | 14.52 | 15.9 | 15.13 | 13.81 | True |
| 2025-12-24 | 002228 | 合兴包装 | 海峡两岸 | 9 | 10 | 0.014 | 1 | 换手板 | 5.95 | 6.39 | 6.17 | 5.54 | True |
| 2025-12-26 | 603278 | 大业股份 | 商业航天 | 11 | 20 | 0.019 | 2 | T字板 | 12.8 | 14.08 | 15.49 | 17.04 | True |
| 2025-12-29 | 002347 | 泰尔股份 | 机器人概念 | 12 | 11 | 0.014 | 9 | 换手板 | 10.23 | 11.25 | 12.38 | 13.14 | True |
| 2025-12-31 | 002413 | 雷科防务 | 商业航天 | 6 | 17 | 0.024 | 1 | 换手板 | 12.55 | 13.81 | 15.19 | 16.71 | True |
| 2026-01-05 | 002757 | 南兴股份 | 人工智能 | 7 | 10 | 0.020 | 2 | 换手板 | 21.42 | 23.36 | 21.41 | 23.57 | True |
| 2026-01-06 | 002151 | 北斗星通 | 商业航天 | 13 | 15 | 0.014 | 1 | 换手板 | 54.97 | 57.7 | 59.69 | 60.82 | True |
| 2026-01-08 | 002202 | 金风科技 | 商业航天 | 10 | 28 | 0.006 | 0 | 换手板 | 29.04 | 31.74 | 34.93 | 33.75 | True |
| 2026-01-09 | 600637 | 东方明珠 | 人工智能 | 11 | 30 | 0.007 | 5 | T字板 | 13.32 | 14.52 | 15.26 | 14.73 | True |
| 2026-01-12 | 603017 | 中衡设计 | 商业航天 | 12 | 43 | 0.019 | 0 | 换手板 | 14.63 | 13.02 | 12.26 | 11.91 | False |
| 2026-01-13 | 603598 | 引力传媒 | 人工智能 | 13 | 31 | 0.016 | 2 | T字板 | 31.37 | 32.4 | 31.51 | 28.36 | True |
| 2026-01-14 | 603000 | 人民网 | 人工智能 | 5 | 35 | 0.013 | 1 | 换手板 | 28.03 | 30.7 | 27.62 | 24.85 | True |
| 2026-01-23 | 002342 | 巨力索具 | 商业航天 | 18 | 17 | 0.021 | 0 | 换手板 | 13.54 | 13.7 | 13.2 | 14.52 | True |
| 2026-01-28 | 000506 | 招金黄金 | 黄金 | 7 | 29 | 0.010 | 1 | 换手板 | 25.93 | 28.52 | 25.67 | 23.1 | True |
| 2026-02-11 | 603980 | 吉华集团 | 化工 | 4 | 16 | 0.004 | 10 | 换手板 | 8.72 | 8.49 | 7.63 | 8.11 | False |
| 2026-02-27 | 002378 | 章源钨业 | 有色金属 | 7 | 15 | 0.005 | 0 | 换手板 | 40.6 | 43.82 | 41.51 | 44.86 | True |
| 2026-03-25 | 600758 | 辽宁能源 | 电力 | 8 | 15 | 0.021 | 3 | T字板 | 5.72 | 6.14 | 5.53 | 4.98 | True |
| 2026-04-07 | 000720 | 新能泰山 | 通信 | 7 | 12 | 0.027 | 0 | 换手板 | 6.53 | 6.7 | 6.03 | 5.43 | True |
| 2026-04-08 | 600654 | 中安科 | 算力 | 4 | 21 | 0.024 | 0 | 换手板 | 4.4 | 4.48 | 4.08 | 4.49 | True |
| 2026-04-16 | 002990 | 盛视科技 | 算力 | 6 | 20 | 0.007 | 16 | 换手板 | 46.32 | 50.85 | 48.9 | 45.05 | True |
| 2026-04-30 | 600379 | 宝光股份 | 芯片 | 4 | 12 | 0.028 | 0 | 换手板 | 16.78 | 18.43 | 17.82 | 16.72 | True |
| 2026-05-08 | 603278 | 大业股份 | 机器人概念 | 4 | 23 | 0.019 | 0 | 换手板 | 14.91 | 15.35 | 15.78 | 15.29 | True |
| 2026-05-11 | 002491 | 通鼎互联 | 通信 | 5 | 16 | 0.008 | 4 | T字板 | 22.73 | 25.0 | 26.95 | 24.65 | True |
| 2026-05-13 | 600396 | 华电辽能 | 电力 | 6 | 17 | 0.007 | 1 | 换手板 | 16.56 | 16.64 | 17.43 | 15.69 | True |
| 2026-05-14 | 002208 | 合肥城建 | 芯片 | 5 | 12 | 0.003 | 7 | 换手板 | 19.8 | 20.76 | 22.84 | 25.12 | True |
| 2026-05-20 | 000417 | 合百集团 | 芯片 | 8 | 26 | 0.038 | 0 | 换手板 | 9.53 | 9.25 | 10.18 | 10.29 | True |
| 2026-05-28 | 002579 | 中京电子 | 通信 | 4 | 17 | 0.016 | 0 | 换手板 | 18.19 | 17.15 | 18.87 | 20.76 | True |
| 2026-06-01 | 002995 | 天地在线 | AI应用 | 4 | 21 | 0.027 | 0 | 换手板 | 25.11 | 26.0 | 25.03 | 23.62 | True |
| 2026-06-05 | 603135 | 中重科技 | 机器人概念 | 5 | 14 | 0.007 | 0 | 换手板 | 14.03 | 15.43 | 15.8 | 14.22 | True |
| 2026-06-16 | 301176 | 逸豪新材 | 通信 | 4 | 25 | 0.000 | 5 | 换手板 | 81.5 | 79.89 | 78.64 | 77.48 | False |
| 2026-06-18 | 002141 | 贤丰控股 | 通信 | 4 | 11 | 0.023 | 0 | 换手板 | 4.71 | 4.5 | 4.95 | 4.76 | True |
| 2026-06-23 | 600851 | 海欣股份 | 医药 | 5 | 14 | 0.008 | 2 | 换手板 | 9.72 | 10.04 | 9.73 | 8.75 | True |
| 2026-06-24 | 603938 | 三孚股份 | 芯片 | 4 | 31 | 0.002 | 2 | 换手板 | 71.63 | 69.68 | 75.81 | 74.98 | True |
| 2026-07-03 | 605189 | 富春染织 | 机器人概念 | 4 | 43 | 0.012 | 0 | 换手板 | 16.05 | 15.16 | 14.55 | 13.8 | False |
| 2026-07-23 | 002879 | 长缆科技 | 智能电网 | 6 | 27 | 0.064 | 2 | 换手板 | 16.41 | 18.05 | 19.86 | 18.9 | True |
| 2026-08-04 | 000815 | 美利云 | 算力 | 7 | 27 | 0.023 | 0 | 换手板 | 18.37 | 18.85 | 18.31 | 18.03 | True |
| 2026-08-06 | 002552 | 宝鼎科技 | 通信 | 10 | 13 | 0.010 | 2 | 换手板 | 43.27 | 47.6 | 52.36 | 54.61 | True |

Honesty notes:

- maxc3 is the mildest priced win (any of the next 3 closes beats t close). It is not next-day profit, not 3-day membership, not a daban fill.
- hold_close on A is 33/42 = 78.6%; on B 36/46 = 78.3%. Those do not claim 90%.
- strongest seal among that day's 3-boards can still be a weak ratio (several picks have seal < 1%).
- The 38/46 grid cell (boards>=4 and seal>=2% and theme_n>=5, all such names, not 1-per-day) remains 82.6% after raw-bar verify. Not replaced; these are name-picks.

## 1. Verify 38/46 cell against raw daily_bars

Rebuilt independently from candidates + THS + daily_bars (same definition as grid_buyable).

- n_base=46, n_with_maxc3=46
- maxc3 38/46 = 82.6% | h1 23/28 = 82.1% | h2 15/18 = 83.3% | claim=False
- raw daily_bars re-read spot-check: 13/13 match
- THS price vs t bar close disagree (>0.02): 13/46. Buy uses THS (grid convention). Using bar close as buy yields 40/46 = 87.0%, still not 90%.
- Number is correct. Not a scheme.

8 losses of the 38/46 cell share no single t-known killer that keeps n>=30 at 90% (high turnover in 4/8 losses; turn 8-25 reaches 28/31 = 90.3% but half2 11/13 = 84.6%).

## 2. Name pick (rest of the scan)

Selectors were deterministic, t-known, yi-zi excluded. Modes: per_day / per_theme_day / per_day_max_theme. theme_n_min in {5,6,8,10,12}.
Full grid: out/name_pick_cells.csv.

Near-misses that failed a gate:

| mode | tn | selector | outcome | n | rate | half1 | half2 | why not claim |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| per_day_max_theme | 10 | tzi_strongest | maxc3 | 30 | 27/30=90.0% | 14/16=87.5% | 13/14=92.9% | half1<90, half2 n<15 |
| per_day | 10 | board3_strongest | maxc3 | 55 | 48/55=87.3% | 23/26=88.5% | 25/29=86.2% | rate<90 |
| per_day | 10 | board3_strongest + turn8-25 | maxc3 | 33 | 30/33=90.9% | 15/16=93.8% | 15/17=88.2% | half2<90 |
| per_day_max_theme | 8 | tzi_strongest | maxc3 | 35 | 31/35=88.6% | 15/18=83.3% | 16/17=94.1% | rate<90 |

T-zi t-bar check: 306 non-yi-zi T-zi names, 302 had a dip (low < close), 7 were OHLC-flat. Stock-level T-zi+theme_n is only 72-82%; the 90% T-zi cell was 1-per-day in the largest theme and failed halves.

## 3. Squeeze the 82.6% neighborhood

No squeeze cell hit 90% with n>=30 and both halves >=90%. Full grid: out/squeeze_cells.csv.

Closest n>=30:

| filters | outcome | n | rate | half1 | half2 |
| --- | --- | --- | --- | --- | --- |
| ge4_seal02_tn5+turn_mid (5-25) | maxc3 | 34 | 30/34=88.2% | 18/20=90.0% | 12/14=85.7% |
| ge4_seal02_tn5+turn 8-25 | maxc3 | 31 | 28/31=90.3% | 17/18=94.4% | 11/13=84.6% |
| ge3 unopened tn>=6 seal>=2% | maxc3 | 31 | 28/31=90.3% | 13/14=92.9% | 15/17=88.2% |
| ge4_seal02_tn5+circ_mid | maxc3 | 37 | 32/37=86.5% | 20/23=87.0% | 12/14=85.7% |

Breadcrumbs (both halves >=90% but n<30):

- ge3 unopened tn>=6 + height_drop: 22/24 = 91.7% (10/11, 12/13)
- ge3 unopened tn>=8 + height_drop: 20/22 = 90.9% (9/10, 11/12)

Adding intact / broken / stronger seal / theme_n>=6/8 / not-zha / H-relative one-at-a-time to the 38/46 cell either drops below n=30 or stays in the mid-80s.

## 4. Auction / daban / timeshare probe

- THS: no auction/tick endpoint in repo. STOCK_LINE /v6/line/hs_{code}/01/ is daily OHLC only (already cached). Did not invent a minute period.
- data/research/auction/observations.jsonl still empty. Contract forbids fabricating auction from close.
- his_daban_list is NOT in the kaipanla backfill contract (backfill = sentiment / expression / zt_pool / sector_ladder only). No mass backfill.
- Tiny probe (2 days, Type=4): KaipanlaClient.his_daban_list ReadTimeout 12s on 2026-07-24 and 2026-01-08. One-off retry 30s -> SSL EOF. No schema, no rows. Dumps: out/daban_probe/.
- Field still missing for auction / huifeng daban fills: live or historically-verified auction prints, and timeshare / open-board prices.

## 5. Files

- out/buyable_hunt2.md (this file)
- out/name_pick_cells.csv
- out/name_pick_claim_members.csv
- out/squeeze_cells.csv
- out/daban_probe/ (timeouts only)
- Prior outputs untouched: buyable_hunt.md, buyable_cells.csv, buyable_grid.csv, candidates.csv, daily_bars/
- script: tools/relay_study/hunt_buyable2.py

