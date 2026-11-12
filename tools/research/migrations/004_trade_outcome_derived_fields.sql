UPDATE trade_outcomes
   SET sell_date = COALESCE(
           json_extract(raw_json, '$."尾盘卖出日期"'),
           json_extract(raw_json, '$."卖出日期"'),
           json_extract(raw_json, '$."卖出时间"')
       ),
       return_pct_micros = CASE
           WHEN COALESCE(
               json_extract(raw_json, '$."尾盘卖出收益率"'),
               json_extract(raw_json, '$."收益率"'),
               json_extract(raw_json, '$."收益率百分比"')
           ) IS NULL THEN NULL
           ELSE CAST(ROUND(COALESCE(
               json_extract(raw_json, '$."尾盘卖出收益率"'),
               json_extract(raw_json, '$."收益率"'),
               json_extract(raw_json, '$."收益率百分比"')
           ) * 1000000) AS INTEGER)
       END;

UPDATE dynamic_research
   SET sell_time = COALESCE(
           json_extract(raw_json, '$."买入后结果"."尾盘卖出日期"'),
           json_extract(raw_json, '$."买入后结果"."卖出日期"'),
           json_extract(raw_json, '$."买入后结果"."卖出时间"')
       ),
       sell_price_milli = CASE
           WHEN COALESCE(
               json_extract(raw_json, '$."买入后结果"."尾盘卖出价格"'),
               json_extract(raw_json, '$."买入后结果"."卖出价格"')
           ) IS NULL THEN NULL
           ELSE CAST(ROUND(COALESCE(
               json_extract(raw_json, '$."买入后结果"."尾盘卖出价格"'),
               json_extract(raw_json, '$."买入后结果"."卖出价格"')
           ) * 1000) AS INTEGER)
       END,
       return_pct_micros = CASE
           WHEN COALESCE(
               json_extract(raw_json, '$."买入后结果"."尾盘卖出收益率"'),
               json_extract(raw_json, '$."买入后结果"."收益率"'),
               json_extract(raw_json, '$."买入后结果"."收益率百分比"')
           ) IS NULL THEN NULL
           ELSE CAST(ROUND(COALESCE(
               json_extract(raw_json, '$."买入后结果"."尾盘卖出收益率"'),
               json_extract(raw_json, '$."买入后结果"."收益率"'),
               json_extract(raw_json, '$."买入后结果"."收益率百分比"')
           ) * 1000000) AS INTEGER)
       END;
