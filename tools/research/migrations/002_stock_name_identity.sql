CREATE TEMP TABLE stock_name_minimums AS
SELECT stock_id, name, MAX(valid_from) AS valid_from
FROM stock_names
GROUP BY stock_id, name;

DELETE FROM stock_names
WHERE id NOT IN (
    SELECT MIN(id)
    FROM stock_names
    GROUP BY stock_id, name
);

UPDATE stock_names AS target
SET valid_from = (
    SELECT minimums.valid_from
    FROM stock_name_minimums AS minimums
    WHERE minimums.stock_id = target.stock_id
      AND minimums.name = target.name
);

DROP TABLE stock_name_minimums;

CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_names_identity
ON stock_names(stock_id, name);
