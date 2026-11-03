// Tests 0006_statements.sql in PGlite: backfill of rows written before it, constraints, and what anon can see.
// cd somewhere && npm i @electric-sql/pglite @electric-sql/pglite-pgvector
// node supabase/test_statements_migration.mjs supabase/migrations   (run from a folder where those packages resolve)
import { PGlite } from '@electric-sql/pglite'
import * as pgv from '@electric-sql/pglite-pgvector'
import fs from 'fs'
import path from 'path'
import assert from 'assert/strict'

const vector = pgv.vector ?? pgv.default ?? pgv.pgvector
const dir = process.argv[2] ?? 'supabase/migrations'
const files = fs.readdirSync(dir).filter((f) => f.endsWith('.sql')).sort()
const before = files.filter((f) => f < '0006')
const after = files.filter((f) => f >= '0006' && f < '0012') // 0012 hides verdicts: see test_sources_migration.mjs
const db = new PGlite({ extensions: { vector } })
await db.exec(`create schema extensions; create role anon; create role authenticated; create role service_role;`)
for (const f of before) await db.exec(fs.readFileSync(path.join(dir, f), 'utf8'))

// Rows as the old pipeline wrote them.
await db.exec(`
insert into episodes (id, youtube_video_id, status) values ('00000000-0000-0000-0000-000000000001','vid1','in_review');
insert into verdicts (id, verdict, confidence, reasoning) values ('00000000-0000-0000-0000-0000000000a1','supported',0.9,'ok');
insert into verdicts (id, verdict, confidence, reasoning, review_status) values ('00000000-0000-0000-0000-0000000000a2','false',0.9,'x','pending');
insert into claims (episode_id, idx, claim_text, pestle_area, claim_type, policy_tier, verdict_id, not_checked_reason) values
  ('00000000-0000-0000-0000-000000000001',0,'verified','economic','fact','normal','00000000-0000-0000-0000-0000000000a1',null),
  ('00000000-0000-0000-0000-000000000001',1,'pending','economic','fact','normal','00000000-0000-0000-0000-0000000000a2',null),
  ('00000000-0000-0000-0000-000000000001',2,'lower priority','economic','fact','normal',null,'not_prioritised'),
  ('00000000-0000-0000-0000-000000000001',3,'opinion','economic','opinion','never',null,'opinion'),
  ('00000000-0000-0000-0000-000000000001',4,'prediction','economic','prediction','never',null,'prediction'),
  ('00000000-0000-0000-0000-000000000001',5,'redacted','social','fact','never',null,'outside_policy'),
  ('00000000-0000-0000-0000-000000000001',6,'story','social','anecdote','never',null,'anecdote');
`)
for (const f of after) await db.exec(fs.readFileSync(path.join(dir, f), 'utf8'))

const rows = (await db.query(`select idx, statement_type, verification_status, not_checked_reason from claims order by idx`)).rows
const want = [
  [0, 'factual_claim', 'verified', null], [1, 'factual_claim', 'awaiting_review', null],
  [2, 'factual_claim', 'not_requested', null], [3, 'opinion', 'not_eligible', 'opinion'],
  [4, 'forecast', 'not_eligible', 'prediction'], [5, 'factual_claim', 'not_eligible', 'outside_policy'],
  [6, 'other', 'not_eligible', 'anecdote'],
]
assert.deepEqual(rows.map((r) => [r.idx, r.statement_type, r.verification_status, r.not_checked_reason]), want)
const counts = (await db.query(`select statement_counts from episodes`)).rows[0].statement_counts
assert.deepEqual(counts, { factual_claim: 4, opinion: 1, forecast: 1, other: 1 })

// Constraints
await assert.rejects(db.exec(`update claims set statement_type = 'rumour' where idx = 0`))
await assert.rejects(db.exec(`update claims set verification_status = 'done' where idx = 0`))

// verify_requests is private; the new columns are public.
await db.exec(`insert into verify_requests (claim_id, episode_id, requester) select id, episode_id, 'h' from claims where idx = 2`)
await db.exec(`set role anon`)
const anonRows = (await db.query(`select statement_type, verification_status, tag_note from claims`)).rows
assert.equal(anonRows.length, 7)
assert.equal((await db.query(`select statement_counts from episodes`)).rows.length, 1)
await assert.rejects(db.query(`select count(*) from verify_requests`)) // revoked, and RLS has no policy
assert.deepEqual((await db.query(`select verdict from verdicts`)).rows.map((r) => r.verdict), ['supported']) // pending stays hidden
await db.exec(`reset role`)
console.log(`ok: ${before.length + after.length} migrations, backfill, constraints and anon visibility`)
