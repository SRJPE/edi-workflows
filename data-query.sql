SELECT DISTINCT ON (gri.sample_id)
    gri.sample_id,
    rt.run_name,
    substring(gri.sample_id FROM '^[^_]+_((?:100|[1-9][0-9]?))_') AS sample_event,
    st.datetime_collected,
    st.fork_length_mm,
    st.field_run_type_id
FROM
    genetic_run_identification gri
JOIN public.run_type rt
ON rt.id = gri.run_type_id
JOIN public.sample st
ON st.id = gri.sample_id
WHERE gri.sample_id LIKE '___24%%'
ORDER BY
    gri.sample_id,
    gri.created_at DESC;

