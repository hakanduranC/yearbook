-- name: SearchMedia :many
-- The one hybrid search statement (docs/CONVENTIONS.md "Hybrid search"): candidates are the top
-- 200 by cosine on media_embeddings, caption full text and trigram tags, fused by reciprocal rank
-- (k = 60); the structured filters of the agent's search_media apply on top. With an empty q the
-- fusion is skipped and order_by decides (recent | best | oldest).
--   scope: event_ids (events the viewer may see) plus the viewer's library when include_library
--   query_vec: null when the embedder is down (text-only fallback)
with vec as (
  select e.media_id, row_number() over (order by e.embedding <=> sqlc.narg('query_vec')::vector) as r
  from media_embeddings e
  join media m on m.id = e.media_id
  where sqlc.narg('query_vec')::vector is not null
    and m.state = 'ready'
    and (m.event_id = any(@event_ids::bytea[]) or (@include_library::boolean and m.owner_id = @user_id::bytea))
  order by e.embedding <=> sqlc.narg('query_vec')::vector
  limit 200
),
fts as (
  select m.id as media_id,
         row_number() over (order by ts_rank(m.caption_tsv, websearch_to_tsquery('simple', @q::text)) desc, m.id) as r
  from media m
  where @q::text <> ''
    and m.state = 'ready'
    and (m.event_id = any(@event_ids::bytea[]) or (@include_library::boolean and m.owner_id = @user_id::bytea))
    and m.caption_tsv @@ websearch_to_tsquery('simple', @q::text)
  limit 200
),
tags as (
  select t.media_id, row_number() over (order by max(similarity(t.tag, @q::text)) desc, t.media_id) as r
  from media_tags t
  join media m on m.id = t.media_id
  where @q::text <> ''
    and m.state = 'ready'
    and (m.event_id = any(@event_ids::bytea[]) or (@include_library::boolean and m.owner_id = @user_id::bytea))
    and t.tag % @q::text
  group by t.media_id
  limit 200
),
fused as (
  select u.media_id, sum(1.0 / (60 + u.r))::real as score
  from (select * from vec union all select * from fts union all select * from tags) u
  group by u.media_id
)
select m.id, coalesce(m.captured_at, m.created_at)::timestamptz as sort_at, coalesce(f.score, 0)::real as score
from media m
left join fused f on f.media_id = m.id
left join media_quality q on q.media_id = m.id
left join events e on e.id = m.event_id
where m.state = 'ready'
  and (m.event_id = any(@event_ids::bytea[]) or (@include_library::boolean and m.owner_id = @user_id::bytea))
  and (@q::text = '' or f.media_id is not null)
  and (sqlc.narg('kind')::text is null or m.kind = sqlc.narg('kind')::text)
  and (sqlc.narg('from_at')::timestamptz is null or coalesce(m.captured_at, m.created_at) >= sqlc.narg('from_at')::timestamptz)
  and (sqlc.narg('to_at')::timestamptz is null or coalesce(m.captured_at, m.created_at) < sqlc.narg('to_at')::timestamptz)
  and (sqlc.narg('day_part')::text is null or
       case
         when extract(hour from coalesce(m.captured_at, m.created_at) at time zone coalesce(e.timezone, 'Europe/Berlin')) between 5 and 10 then 'morning'
         when extract(hour from coalesce(m.captured_at, m.created_at) at time zone coalesce(e.timezone, 'Europe/Berlin')) between 11 and 16 then 'afternoon'
         when extract(hour from coalesce(m.captured_at, m.created_at) at time zone coalesce(e.timezone, 'Europe/Berlin')) between 17 and 21 then 'evening'
         else 'night'
       end = sqlc.narg('day_part')::text)
  and (cardinality(@people_all::bytea[]) = 0 or not exists (
        select 1 from unnest(@people_all::bytea[]) as want(pid)
        where not exists (select 1 from faces f2 where f2.media_id = m.id and f2.person_id = want.pid)))
  and (cardinality(@people_any::bytea[]) = 0 or exists (
        select 1 from faces f2 where f2.media_id = m.id and f2.person_id = any(@people_any::bytea[])))
  and (cardinality(@people_exclude::bytea[]) = 0 or not exists (
        select 1 from faces f2 where f2.media_id = m.id and f2.person_id = any(@people_exclude::bytea[])))
  and (not @me::boolean or exists (
        select 1 from faces f2 join person_links pl on pl.person_id = f2.person_id
        where f2.media_id = m.id and pl.identity_id = @identity_id::bytea))
  and (not @uploaded_by_me::boolean or m.uploader_user = @user_id::bytea or m.uploader_guest = @guest_id::bytea)
  and (not @liked_by_me::boolean or exists (select 1 from likes l where l.media_id = m.id and l.actor = @actor::bytea))
  and (sqlc.narg('faces_min')::int is null or (select count(*) from faces f2 where f2.media_id = m.id) >= sqlc.narg('faces_min')::int)
  and (sqlc.narg('faces_max')::int is null or (select count(*) from faces f2 where f2.media_id = m.id) <= sqlc.narg('faces_max')::int)
  and (sqlc.narg('min_score')::real is null or q.score >= sqlc.narg('min_score')::real)
  and (cardinality(@tags::text[]) = 0 or exists (
        select 1 from media_tags t where t.media_id = m.id and lower(t.tag) = any(@tags::text[])))
  and ((sqlc.narg('age_min')::int is null and sqlc.narg('age_max')::int is null) or exists (
        select 1 from faces f2
        left join person_links pl on pl.person_id = f2.person_id
        left join identities i on i.id = pl.identity_id
        where f2.media_id = m.id
          and (@age_mode::text <> 'exact' or (i.birthdate is not null and m.captured_at is not null))
          and (@age_mode::text <> 'estimated' or i.birthdate is null)
          and coalesce(
                case when i.birthdate is not null and m.captured_at is not null
                     then extract(year from age(m.captured_at, i.birthdate))::real end,
                f2.age_est) between coalesce(sqlc.narg('age_min')::int, 0) and coalesce(sqlc.narg('age_max')::int, 200)))
  and (@include_dups::boolean or m.is_best_of_dup)
order by
  case when @q::text <> '' then f.score end desc nulls last,
  case when @order_by::text = 'best' then coalesce(q.score, -1) end desc,
  case when @order_by::text = 'oldest' then coalesce(m.captured_at, m.created_at) end asc,
  coalesce(m.captured_at, m.created_at) desc, m.id desc
limit @row_limit;

-- name: ListVisibleEventIDs :many
-- Events the caller may see: owned, member of, or entered as a guest (by cookie, or by a cookie
-- that was later tied to the account).
select e.id
from events e
where e.archived_at is null
  and ((@user_id::bytea is not null and (e.owner_id = @user_id::bytea
          or exists (select 1 from event_members em where em.event_id = e.id and em.user_id = @user_id::bytea)
          or exists (select 1 from guests g join guest_cookies gc on gc.id = g.cookie_id where g.event_id = e.id and gc.user_id = @user_id::bytea)))
    or (@cookie_id::bytea is not null and exists (select 1 from guests g where g.event_id = e.id and g.cookie_id = @cookie_id::bytea)))
order by e.starts_at desc;

-- name: SearchPersonsByName :many
-- resolve_people: named persons in the given events whose name matches q (prefix, substring or trigram).
select p.id, p.event_id, p.display_name, p.cover_face, p.face_count, p.hidden, e.slug as event_slug,
       greatest(similarity(coalesce(p.display_name, ''), @q::text),
                case when lower(coalesce(p.display_name, '')) like lower(@q::text) || '%' then 0.9 else 0 end,
                case when lower(coalesce(p.display_name, '')) like '%' || lower(@q::text) || '%' then 0.7 else 0 end)::real as rank
from persons p
join events e on e.id = p.event_id
where p.event_id = any(@event_ids::bytea[])
  and p.display_name is not null
  and p.face_count > 0
  and not p.hidden
  and (lower(p.display_name) like '%' || lower(@q::text) || '%' or p.display_name % @q::text)
order by rank desc, p.face_count desc
limit 10;

-- name: ListPersonsByIDs :many
select p.id, p.event_id, p.display_name, p.cover_face, p.face_count, p.hidden, p.created_at,
       pl.identity_id,
       coalesce(pl.identity_id = @identity_id::bytea, false)::boolean as is_me,
       (select count(distinct f.media_id) from faces f where f.person_id = p.id)::int as media_count,
       e.slug as event_slug
from persons p
join events e on e.id = p.event_id
left join person_links pl on pl.person_id = p.id
where p.id = any(@ids::bytea[]);
