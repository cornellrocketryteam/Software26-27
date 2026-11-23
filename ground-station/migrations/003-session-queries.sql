BEGIN;
-- No session here is designated active: receipt recency is not boot order.
CREATE OR REPLACE VIEW public.telemetry_sessions AS
SELECT unit_id, publisher_session_hi, publisher_session_lo,
       lpad(to_hex(div(publisher_session_hi,4294967296)::bigint),8,'0') ||
       lpad(to_hex(mod(publisher_session_hi,4294967296)::bigint),8,'0') ||
       lpad(to_hex(div(publisher_session_lo,4294967296)::bigint),8,'0') ||
       lpad(to_hex(mod(publisher_session_lo,4294967296)::bigint),8,'0') AS session_id,
       min(publisher_sequence) AS first_sequence,
       max(publisher_sequence) AS last_sequence,
       count(*) AS stored_frames,
       min(received_at) AS first_received_at,
       max(received_at) AS last_received_at
FROM public.telemetry_data WHERE source_identity_valid
GROUP BY unit_id, publisher_session_hi, publisher_session_lo;

CREATE OR REPLACE FUNCTION public.telemetry_session_head(
    selected_unit INTEGER, session_hi NUMERIC, session_lo NUMERIC)
RETURNS SETOF public.telemetry_data
LANGUAGE plpgsql STABLE SECURITY INVOKER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    IF selected_unit IS DISTINCT FROM 0 OR session_hi IS NULL OR session_lo IS NULL
       OR NOT (session_hi BETWEEN 0 AND 18446744073709551615 AND session_hi = trunc(session_hi))
       OR NOT (session_lo BETWEEN 0 AND 18446744073709551615 AND session_lo = trunc(session_lo))
       OR (session_hi = 0 AND session_lo = 0) THEN
        RAISE EXCEPTION 'Expected a known-v1 fill-station session with exact uint64 halves' USING ERRCODE = '22023';
    END IF;
    RETURN QUERY SELECT d.* FROM public.telemetry_latest_in_session d
    WHERE d.unit_id = selected_unit AND d.publisher_session_hi = session_hi
      AND d.publisher_session_lo = session_lo;
END;
$$;

CREATE OR REPLACE FUNCTION public.telemetry_session_history(
    selected_unit INTEGER, session_hi NUMERIC, session_lo NUMERIC,
    after_sequence NUMERIC DEFAULT 0, page_size INTEGER DEFAULT 100)
RETURNS SETOF public.telemetry_event_history
LANGUAGE plpgsql STABLE SECURITY INVOKER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    -- Validate even absent sessions. Never round fractional identifiers/cursors.
    IF selected_unit IS DISTINCT FROM 0 OR session_hi IS NULL OR session_lo IS NULL
       OR NOT (session_hi BETWEEN 0 AND 18446744073709551615 AND session_hi = trunc(session_hi))
       OR NOT (session_lo BETWEEN 0 AND 18446744073709551615 AND session_lo = trunc(session_lo))
       OR (session_hi = 0 AND session_lo = 0)
       OR after_sequence IS NULL
       OR NOT (after_sequence BETWEEN 0 AND 18446744073709551615 AND after_sequence = trunc(after_sequence))
       OR page_size IS NULL OR page_size NOT BETWEEN 1 AND 1000 THEN
        RAISE EXCEPTION 'Invalid session, uint64 sequence cursor or page size (1..1000)' USING ERRCODE = '22023';
    END IF;
    RETURN QUERY SELECT d.* FROM public.telemetry_event_history d
    WHERE d.source_identity_valid AND d.unit_id = selected_unit
      AND d.publisher_session_hi = session_hi AND d.publisher_session_lo = session_lo
      AND d.publisher_sequence > after_sequence
    ORDER BY d.publisher_sequence ASC LIMIT page_size;
END;
$$;
REVOKE ALL ON public.telemetry_sessions FROM PUBLIC;
REVOKE ALL ON FUNCTION public.telemetry_session_head(INTEGER,NUMERIC,NUMERIC) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.telemetry_session_history(INTEGER,NUMERIC,NUMERIC,NUMERIC,INTEGER) FROM PUBLIC;
COMMIT;
