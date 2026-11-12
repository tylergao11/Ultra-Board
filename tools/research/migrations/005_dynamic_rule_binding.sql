ALTER TABLE dynamic_research ADD COLUMN rule_set_id INTEGER REFERENCES rule_sets(id);

UPDATE dynamic_research
   SET rule_set_id = (
       SELECT plan.rule_set_id
         FROM research_plans AS plan
        WHERE plan.id = dynamic_research.plan_id
   )
 WHERE rule_set_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_dynamic_rule_set ON dynamic_research(rule_set_id);
