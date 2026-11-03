// Tests 0012 and 0013 in PGlite: old verdicts hidden, tags merged, sources public (any site, in search order),
// empty lookups reopened, private tables private.
// cd somewhere && npm i @electric-sql/pglite @electric-sql/pglite-pgvector
// node supabase/test_sources_migration.mjs supabase/migrations   (run from a folder where those packages resolve)
import { PGlite } from '@electric-sql/pglite'
import * as pgv from '@electric-sql/pglite-pgvector'
import fs from 'fs'
import path from 'path'
import assert from 'assert/strict'

const vector = pgv.vector ?? pgv.default ?? pgv.pgvector
const dir = process.argv[2] ?? 'supabase/migrations'
const files = fs.readdirSync(dir).filter((f) => f.endsWith('.sql')).sort()
const before = files.filter((f) => f < '0012')
const v12 = files.filter((f) => f >= '0012' && f < '0013')
const after = files.filter((f) => f >= '0013')
const db = new PGlite({ extensions: { vector } })
await db.exec(`create schema extensions; create role anon; create role authenticated; create role service_role;`)
for (const f of before) await db.exec(fs.readFileSync(path.join(dir, f), 'utf8'))

// Rows as the verdict-era pipeline wrote them.
const EP = '00000000-0000-0000-0000-000000000001'
await db.exec(`
insert into channels (id, youtube_channel_id, name, track, avatar_url) values ('00000000-0000-0000-0000-0000000000c1','UC1','Chan','politics','https://yt3/a.jpg');
insert into episodes (id, youtube_video_id, status, channel_id, tally) values ('${EP}','vid1','done','00000000-0000-0000-0000-0000000000c1','{"supported":1}');
insert into verdicts (id, verdict, confidence, reasoning) values ('00000000-0000-0000-0000-0000000000a1','supported',0.9,'ok');
insert into citations (verdict_id, url, tier, quote, quote_check_passed) values ('00000000-0000-0000-0000-0000000000a1','https://pib.gov.in/x',1,'q',true);
insert into claims (episode_id, idx, claim_text, pestle_area, claim_type, policy_tier, verdict_id, statement_type, tag_note, not_checked_reason) values
  ('${EP}',0,'verified claim','economic','fact','normal','00000000-0000-0000-0000-0000000000a1','factual_claim',null,null),
  ('${EP}',1,'plain claim','economic','fact','normal',null,'factual_claim',null,null),
  ('${EP}',2,'redacted','social','fact','never',null,'factual_claim',null,'outside_policy'),
  ('${EP}',3,'hearsay','economic','opinion','normal',null,'hearsay','vague source','hearsay'),
  ('${EP}',4,'analogy','economic','opinion','normal',null,'analogy','compares','analogy'),
  ('${EP}',5,'loaded','economic','opinion','normal',null,'loaded_language','charged','loaded_language'),
  ('${EP}',6,'opinion','economic','opinion','normal',null,'opinion',null,'opinion');
update episodes e set statement_counts = (select jsonb_object_agg(statement_type, n) from (select statement_type, count(*) n from claims group by 1) t);
`)
for (const f of v12) await db.exec(fs.readFileSync(path.join(dir, f), 'utf8'))

// Lookups as the 0012-era pipeline saved them: claim 1 found one checked quote, claim 0 found nothing.
await db.exec(`insert into claim_sources (claim_id, url, title, tier, quote) select id, 'https://mospi.gov.in/a', 'MoSPI', 1, 'GDP grew 7.2 per cent in 2023-24.' from claims where idx = 1`)
await db.exec(`update claims set sources_status = 'done' where idx in (0, 1)`)
for (const f of after) await db.exec(fs.readFileSync(path.join(dir, f), 'utf8'))

// Tags merged, counts recomputed, sources status backfilled.
const rows = (await db.query(`select idx, statement_type, sources_status from claims order by idx`)).rows
assert.deepEqual(rows.map((r) => [r.idx, r.statement_type, r.sources_status]), [
  [0, 'factual_claim', 'not_requested'], [1, 'factual_claim', 'done'], [2, 'factual_claim', 'not_eligible'],
  [3, 'other', 'not_eligible'], [4, 'other', 'not_eligible'], [5, 'other', 'not_eligible'], [6, 'opinion', 'not_eligible'],
])
assert.deepEqual((await db.query(`select statement_counts from episodes`)).rows[0].statement_counts,
  { factual_claim: 3, other: 3, opinion: 1 })
assert.equal((await db.query(`select avatar_url from channels`)).rows[0].avatar_url, null)

// Constraints
await assert.rejects(db.exec(`update claims set sources_status = 'verified' where idx = 0`))
await assert.rejects(db.exec(`insert into claim_sources (claim_id, url, tier, excerpt) select id, 'u', 4, 'q' from claims where idx = 1`))
await db.exec(`update episodes set status = 'removed' where id = '${EP}'`)
await db.exec(`update episodes set status = 'done' where id = '${EP}'`)

// Data the service writes.
// The old quote became the excerpt; any site tier is allowed now, in search order.
assert.equal((await db.query(`select excerpt from claim_sources`)).rows[0].excerpt, 'GDP grew 7.2 per cent in 2023-24.')
await db.exec(`insert into claim_sources (claim_id, url, title, tier, excerpt, rank) select id, 'https://en.wikipedia.org/wiki/GDP', 'Wikipedia', 3, 'Other source.', 1 from claims where idx = 1`)
await db.exec(`insert into source_requests (claim_id, episode_id, requester, kind) select id, episode_id, 'h', 'one' from claims where idx = 1`)
await db.exec(`insert into feedback (claim_id, note, kind) select id, 'wrong speaker', 'wrong_speaker' from claims where idx = 1`)

// What the public can see.
await db.exec(`set role anon`)
const pub = (await db.query(`select id, statement_type, sources_status, sources_error, context_quote, speaker from claims`)).rows
assert.equal(pub.length, 7)
await assert.rejects(db.query(`select tag_note from claims`), 'tag notes are hidden')
await assert.rejects(db.query(`select verdict_id from claims`), 'verdict links are hidden')
await assert.rejects(db.query(`select verification_status from claims`))
await assert.rejects(db.query(`select * from verdicts`), 'old verdicts are hidden')
await assert.rejects(db.query(`select * from citations`))
await assert.rejects(db.query(`select tally from episodes`))
await assert.rejects(db.query(`select count(*) from source_requests`))
await assert.rejects(db.query(`select count(*) from feedback`))
assert.deepEqual((await db.query(`select tier from claim_sources order by rank`)).rows.map((r) => r.tier), [1, 3])
assert.equal((await db.query(`select sources_batch_status, statement_counts from episodes`)).rows.length, 1)
await db.exec(`reset role`)

// Removed and processing visibility: sources of a removed video disappear with it.
await db.exec(`update episodes set status = 'removed' where id = '${EP}'`)
await db.exec(`set role anon`)
assert.equal((await db.query(`select * from claim_sources`)).rows.length, 0)
assert.equal((await db.query(`select id from episodes`)).rows.length, 0)
await db.exec(`reset role`)
console.log(`ok: ${before.length + v12.length + after.length} migrations; verdicts hidden, tags merged, sources public, private tables private`)
