// Tests the migrations in PGlite (embedded Postgres + pgvector) with stand-ins for Supabase roles.
// npm i @electric-sql/pglite @electric-sql/pglite-pgvector && node test_migration.mjs migrations/0001_init.sql migrations/0002_review.sql
import { PGlite } from '@electric-sql/pglite'
import * as pgv from '@electric-sql/pglite-pgvector'
const vector = pgv.vector ?? pgv.default ?? pgv.pgvector
import fs from 'fs'
const db = new PGlite({ extensions: { vector } })
await db.exec(`create schema extensions; create role anon; create role authenticated; create role service_role;`)
const sql = process.argv.slice(2).map((f) => fs.readFileSync(f, 'utf8')).join('\n')
await db.exec(sql)
const v = '[' + Array(768).fill(0).map((_, i) => (i === 0 ? 1 : 0)).join(',') + ']'
await db.exec(`
insert into channels (youtube_channel_id, name, track, perceived_lean) values ('UC1','Demo','politics','critical');
insert into episodes (id, youtube_video_id, status, tally) values ('00000000-0000-0000-0000-000000000001','vid1','done','{"supported":1}');
insert into verdicts (id, verdict, confidence, reasoning) values ('00000000-0000-0000-0000-0000000000a1','supported',0.9,'ok');
insert into verdicts (id, verdict, confidence, reasoning, review_status) values ('00000000-0000-0000-0000-0000000000a2','false',0.9,'x','pending');
insert into claims (episode_id, idx, claim_text, pestle_area, claim_type, policy_tier, embedding, verdict_id)
  values ('00000000-0000-0000-0000-000000000001',0,'4 crore houses','political','fact','stricter','${v}','00000000-0000-0000-0000-0000000000a1'),
         ('00000000-0000-0000-0000-000000000001',1,'GDP 12%','economic','fact','normal','${v}','00000000-0000-0000-0000-0000000000a2');
insert into citations (verdict_id, url, tier, quote, quote_check_passed) values ('00000000-0000-0000-0000-0000000000a1','https://pib.gov.in',1,'q',true);
`)
console.log('match:', (await db.query(`select verdict_id, similarity from match_verdict('${v}', 0.92, 90)`)).rows)
console.log('miss:', (await db.query(`select count(*) from match_verdict('[${Array(768).fill(0).map((_,i)=>i===1?1:0).join(',')}]', 0.92, 90)`)).rows)
await db.exec(`grant usage on schema public to anon; grant select on all tables in schema public to anon;`)
// re-apply column restrictions (grant all above re-opens them, mimic Supabase defaults then our migration order)
await db.exec(`revoke select on channels, episodes from anon; grant select (id, youtube_channel_id, name, track, active, created_at) on channels to anon;
grant select (id, youtube_video_id, channel_id, title, duration_s, published_at, worthiness_score, status, skip_reason, tally, not_checked, created_at, updated_at) on episodes to anon;`)
await db.exec(`set role anon`)
console.log('anon verdicts visible:', (await db.query(`select verdict from verdicts`)).rows)
console.log('anon claims:', (await db.query(`select claim_text, verdict_id from claims order by idx`)).rows.length)
console.log('anon guardrail rows:', (await db.query(`select count(*) from guardrail_events`)).rows)
try { await db.query(`select perceived_lean from channels`); console.log('LEAK') } catch (e) { console.log('perceived_lean hidden:', e.message.slice(0,50)) }
try { await db.query(`select cost_usd from episodes`); console.log('LEAK') } catch (e) { console.log('cost hidden:', e.message.slice(0,50)) }
console.log('anon channel name:', (await db.query(`select name from channels`)).rows)
