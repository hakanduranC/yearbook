#!/bin/sh
# Creates the two buckets and applies CORS. Idempotent; re-run with `docker compose run --rm s3-init`.
set -e
EP=http://s3:8333
for i in $(seq 1 40); do
  if aws --endpoint-url $EP s3 ls >/dev/null 2>&1; then break; fi
  sleep 1
done
for b in yearbook-private yearbook-public; do
  aws --endpoint-url $EP s3api head-bucket --bucket $b >/dev/null 2>&1 || aws --endpoint-url $EP s3 mb s3://$b
done
aws --endpoint-url $EP s3api put-bucket-cors --bucket yearbook-private --cors-configuration file:///cors.json
aws --endpoint-url $EP s3api put-bucket-cors --bucket yearbook-public --cors-configuration file:///cors.json
echo "s3 buckets ready"
