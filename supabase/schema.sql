-- 수저맵 이용자 제보 · 가격 확인 테이블
-- Supabase → SQL Editor → New query 에 전체를 붙여넣고 Run 하세요.

create table if not exists public.submissions (
  id          bigint generated always as identity primary key,
  created_at  timestamptz not null default now(),
  kind        text not null check (kind in ('new_shop', 'price', 'confirm', 'closed')),
  shop_ref    text check (char_length(shop_ref) <= 64),          -- 지도에 있는 가게 id (없으면 새 가게)
  shop_name   text not null check (char_length(shop_name) between 1 and 60),
  addr        text check (char_length(addr) <= 120),
  lat         double precision check (lat between 33 and 39),
  lng         double precision check (lng between 124 and 132),
  cat         text check (cat in ('한식', '중식', '일식', '양식', '기타요식업')),
  menu_name   text check (char_length(menu_name) <= 40),
  price       integer check (price between 500 and 100000),
  note        text check (char_length(note) <= 200),
  device_id   text check (char_length(device_id) <= 64),
  status      text not null default 'pending' check (status in ('pending', 'approved', 'rejected'))
);

create index if not exists submissions_status_idx on public.submissions (status, created_at desc);
create index if not exists submissions_device_idx on public.submissions (device_id, created_at desc);

alter table public.submissions enable row level security;

-- 누구나 제보할 수 있어요. '맞아요' 확인은 바로 반영, 나머지는 검토 대기로만 들어가요.
drop policy if exists "anyone can submit" on public.submissions;
create policy "anyone can submit" on public.submissions
  for insert to anon, authenticated
  with check ((kind = 'confirm' and status = 'approved') or (kind <> 'confirm' and status = 'pending'));

-- 원본 테이블은 밖에서 읽을 수 없어요. (기기 id 보호) 대신 승인된 것만 아래 뷰로 공개해요.
drop view if exists public.public_reports;
create view public.public_reports as
  select id, created_at, kind, shop_ref, shop_name, addr, lat, lng, cat, menu_name, price
  from public.submissions
  where status = 'approved';
grant select on public.public_reports to anon, authenticated;

-- 같은 기기에서 하루 30건까지만 받아요. (도배 방지)
create or replace function public.limit_submissions() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.device_id is null then
    raise exception 'device_id required';
  end if;
  if (select count(*) from public.submissions
      where device_id = new.device_id and created_at > now() - interval '1 day') >= 30 then
    raise exception 'too many submissions today';
  end if;
  return new;
end $$;

drop trigger if exists trg_limit_submissions on public.submissions;
create trigger trg_limit_submissions before insert on public.submissions
  for each row execute function public.limit_submissions();
