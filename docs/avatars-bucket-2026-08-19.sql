-- Applied: the profile-photo bucket, 2026-08-19. Run in the Supabase SQL editor.
--
-- NOT APPLIED BY ANYTHING AUTOMATIC, and that is deliberate. This creates the
-- project's FIRST storage bucket (`select id from storage.buckets` is empty
-- today) and its first storage RLS policies, in a product mid-way through a
-- Google restricted-scope review. New security surface of that kind gets read
-- before it gets run. Until it is run, the product degrades honestly rather
-- than breaking: a Google user's photo still appears (it never touches this
-- bucket -- see apps/web/lib/profile/avatar.ts), the upload control answers
-- "Photo uploads aren't enabled on this deployment yet", and closing an
-- account treats a missing bucket as "no photos to remove" instead of refusing.
--
-- WHAT IT CREATES
--
-- 1. A bucket named `avatars`, public-read, capped at 512 KB per object and
--    limited to the two formats the browser can produce.
--
--    PUBLIC-READ IS A DECISION. The object URL is visible in the page (it is
--    the `url` parameter of the /_next/image request), so a private bucket
--    would mean signed URLs -- which expire, which changes the URL on every
--    render, which defeats the image cache the whole design leans on. Instead
--    the path is `<user id>/<uuid v4>.<ext>`: 122 bits of randomness, so the
--    URL is unguessable, and it is only ever handed to the account that owns
--    it. That is the same trade Google, GitHub and Gravatar make for the same
--    artifact. Nothing else may go in this bucket.
--
--    The size and MIME limits are a SECOND fence, not the only one: every
--    upload goes through apps/web/app/api/profile/avatar/route.ts, which reads
--    the file's own signature rather than the client's declared content type.
--    `allowed_mime_types` here can only check what the uploader claims.
--
-- 2. Four policies on storage.objects, all scoped to this bucket:
--    - read:   the owner's own folder (what account deletion enumerates with;
--              anonymous reads of a public bucket do not go through RLS).
--    - write:  insert / update / delete, restricted to a folder named for the
--              caller's own uid, so the database enforces ownership rather
--              than the route handler being trusted to.
--
--    `(select auth.uid())`, not a bare `auth.uid()`: the subselect is what lets
--    Postgres hoist the call to an InitPlan and evaluate it once per statement
--    instead of once per row -- the same form all 54 policies in this estate
--    were moved to on 2026-08-07.
--
-- REVERSING IT. `delete from storage.objects where bucket_id = 'avatars';`
-- then `delete from storage.buckets where id = 'avatars';` and drop the four
-- policies. Any account holding `custom_avatar_path` in its user metadata then
-- falls back to its Google photo or its monogram on the next render, with no
-- broken image: the tile draws the letter under the photo for exactly this
-- class of reason.

begin;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('avatars', 'avatars', true, 524288, array['image/webp', 'image/png'])
on conflict (id) do nothing;

-- storage.objects already has RLS enabled by Supabase; these are additive.

create policy "avatars: read own folder"
  on storage.objects for select
  to authenticated
  using (
    bucket_id = 'avatars'
    and (select auth.uid())::text = (storage.foldername(name))[1]
  );

create policy "avatars: insert own folder"
  on storage.objects for insert
  to authenticated
  with check (
    bucket_id = 'avatars'
    and (select auth.uid())::text = (storage.foldername(name))[1]
  );

create policy "avatars: update own folder"
  on storage.objects for update
  to authenticated
  using (
    bucket_id = 'avatars'
    and (select auth.uid())::text = (storage.foldername(name))[1]
  )
  with check (
    bucket_id = 'avatars'
    and (select auth.uid())::text = (storage.foldername(name))[1]
  );

create policy "avatars: delete own folder"
  on storage.objects for delete
  to authenticated
  using (
    bucket_id = 'avatars'
    and (select auth.uid())::text = (storage.foldername(name))[1]
  );

commit;

-- Verify (expect one bucket row, and four policies named above):
--
--   select id, public, file_size_limit, allowed_mime_types
--     from storage.buckets where id = 'avatars';
--
--   select policyname, cmd from pg_policies
--    where schemaname = 'storage' and tablename = 'objects'
--      and policyname like 'avatars:%'
--    order by policyname;
--
-- Then, signed in as a user with no photo: Settings -> Profile -> Upload a
-- photo. The tile fills, the sidebar's tile fills after the refresh, and
--
--   select name, owner_id from storage.objects where bucket_id = 'avatars';
--
-- shows one object under that user's id. Remove it and the row goes away --
-- the object is deleted, not just dereferenced.
