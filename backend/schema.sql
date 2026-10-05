CREATE TABLE IF NOT EXISTS sensor_readings (
    reading_id SERIAL PRIMARY KEY,
    node_id VARCHAR(10) NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    water_level_cm DECIMAL(6,2),
    flow_rate_lpm DECIMAL(6,2),
    mq4_voltage DECIMAL(6,3),
    mq135_voltage DECIMAL(6,3),
    label VARCHAR(20),
    trial_id VARCHAR(30)
);

CREATE INDEX IF NOT EXISTS idx_node_timestamp ON sensor_readings (node_id, timestamp);