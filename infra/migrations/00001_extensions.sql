-- +goose Up
create extension if not exists vector;
create extension if not exists pg_trgm;
create extension if not exists citext;

-- +goose Down
drop extension if exists citext;
drop extension if exists pg_trgm;
drop extension if exists vector;
