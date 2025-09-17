CREATE TABLE drivers (
    id SERIAL PRIMARY KEY,
    driver_ref TEXT UNIQUE,
    given_name TEXT NOT NULL,
    family_name TEXT NOT NULL,
    code TEXT, -- 3-letter code (HAM, VER, etc.)
    nationality TEXT,
    date_of_birth DATE,
    team_id INT REFERENCES teams(id)
);

CREATE TABLE teams (
    id SERIAL PRIMARY KEY,
    team_ref TEXT UNIQUE,
    name TEXT NOT NULL,
    nationality TEXT
);

CREATE TABLE races (
    id SERIAL PRIMARY KEY,
    season INT NOT NULL,
    round INT NOT NULL,
    race_name TEXT NOT NULL,
    circuit_name TEXT,
    date DATE,
    location TEXT,
    country TEXT
);

CREATE TABLE lap_times (
    id SERIAL PRIMARY KEY,
    race_id INT NOT NULL REFERENCES races(id),
    driver_id INT NOT NULL REFERENCES drivers(id),
    lap_number INT NOT NULL,
    position INT,
    lap_time_ms INT,
    UNIQUE(race_id, driver_id, lap_number)
);

CREATE TABLE aggregations (
    id SERIAL PRIMARY KEY,
    driver_id INT NOT NULL REFERENCES drivers(id),
    race_id INT NOT NULL REFERENCES races(id),
    avg_lap_ms INT,
    pit_stops INT,
    fastest_lap_ms INT,
    UNIQUE(driver_id, race_id)
);

-- Will add later when I implement live telemetry
CREATE TABLE telemetry (
    id BIGSERIAL PRIMARY KEY,
    race_id INT REFERENCES races(id),
    driver_id INT REFERENCES drivers(id),
    lap_number INT,
    distance_m DECIMAL,
    speed_kph DECIMAL,
    throttle_percent DECIMAL,
    brake BOOLEAN,
    gear INT,
    is_pitting BOOLEAN DEFAULT FALSE,
    drs BOOLEAN
);

CREATE INDEX idx_lap_times_race_driver ON lap_times(race_id, driver_id);
CREATE INDEX idx_aggregations_driver ON aggregations(driver_id);
