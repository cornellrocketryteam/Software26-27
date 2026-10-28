-- Safe to apply repeatedly to the existing TimescaleDB/PostgreSQL telemetry table.
-- Existing rows and legacy publishers have availability_version=0 and retain
-- their original interpretation. Never apply fill-station masks to flight units.
BEGIN;
ALTER TABLE telemetry_data
    ADD COLUMN IF NOT EXISTS availability_version BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS configured_devices_mask BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS valid_readings_mask BIGINT NOT NULL DEFAULT 0;

CREATE OR REPLACE FUNCTION normalize_fill_hardware_availability()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- Explicit NULL metadata from an older connector is legacy, too.
    NEW.availability_version := COALESCE(NEW.availability_version, 0);
    NEW.configured_devices_mask := COALESCE(NEW.configured_devices_mask, 0);
    NEW.valid_readings_mask := COALESCE(NEW.valid_readings_mask, 0);
    IF NEW.unit_id = 0 AND NEW.availability_version = 1 THEN
        IF (NEW.valid_readings_mask & 1) = 0 THEN NEW.pt_1_pressure := NULL; END IF;
        IF (NEW.valid_readings_mask & 2) = 0 THEN NEW.pt_2_pressure := NULL; END IF;
        IF (NEW.valid_readings_mask & 4) = 0 THEN NEW.load_cell := NULL; END IF;
        IF (NEW.configured_devices_mask & 1024) = 0 THEN NEW.ball_valve_open := NULL; END IF;
        IF (NEW.configured_devices_mask & 16) = 0 THEN NEW.sv_1_open := NULL; END IF;
        IF (NEW.configured_devices_mask & 3) = 0 THEN NEW.ignition := NULL; END IF;
        IF (NEW.configured_devices_mask & 2048) = 0 THEN NEW.qd_state := NULL; END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS fill_hardware_availability ON telemetry_data;
CREATE TRIGGER fill_hardware_availability
BEFORE INSERT OR UPDATE ON telemetry_data
FOR EACH ROW EXECUTE FUNCTION normalize_fill_hardware_availability();
COMMIT;
