CREATE TABLE IF NOT EXISTS config (
 key text PRIMARY KEY, value numeric, text_value text, valid_from date DEFAULT CURRENT_DATE
);
CREATE TABLE IF NOT EXISTS employee (
 employee_id integer PRIMARY KEY, last_name text, first_name text, birth_date date, bu text,
 hire_date date, gross_salary numeric(12,2), contract_type text, paid_leave_days integer,
 home_address text, commute_mode text, declared_sport text
);
CREATE TABLE IF NOT EXISTS activity (
 activity_id bigserial PRIMARY KEY, employee_id integer REFERENCES employee(employee_id),
 start_at timestamp NOT NULL, sport_type text NOT NULL, distance_m integer,
 end_at timestamp NOT NULL, elapsed_s integer NOT NULL, comment text,
 CHECK (distance_m IS NULL OR distance_m >= 0), CHECK (end_at >= start_at), CHECK (elapsed_s >= 0)
);
CREATE TABLE IF NOT EXISTS pipeline_run (
 run_id bigserial PRIMARY KEY, started_at timestamp DEFAULT now(), ended_at timestamp,
 status text, rows_loaded integer, error_message text
);
INSERT INTO config(key,value,text_value) VALUES
 ('prime_rate',0.05,NULL),('wellbeing_activity_threshold',15,NULL),('wellbeing_days',5,NULL),
 ('walk_max_km',15,NULL),('bike_max_km',25,NULL)
ON CONFLICT (key) DO NOTHING;
