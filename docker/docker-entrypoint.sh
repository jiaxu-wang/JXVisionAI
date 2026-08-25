#!/bin/sh
set -e
cd /app

# 时区：VISIONAI_TIMEZONE > config.ini [basic] timezone > TZ > Asia/Shanghai
_tz="${VISIONAI_TIMEZONE:-}"
if [ -z "$_tz" ] && [ -f /app/config/config.ini ]; then
  _tz="$(awk -F= '
    /^\[/{sect=$0}
    sect ~ /^\[basic\]/ && $1 ~ /^[[:space:]]*timezone[[:space:]]*$/ {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", $2);
      print $2; exit
    }
  ' /app/config/config.ini)"
fi
if [ -z "$_tz" ]; then
  _tz="${TZ:-Asia/Shanghai}"
fi
export TZ="$_tz"
export VISIONAI_TIMEZONE="$_tz"
if [ -f "/usr/share/zoneinfo/$_tz" ]; then
  ln -snf "/usr/share/zoneinfo/$_tz" /etc/localtime
  echo "$_tz" > /etc/timezone 2>/dev/null || true
fi

role="${1:-${VISIONAI_ROLE:-api}}"
case "$role" in
  api|worker|alert|alert_worker|sip)
    ;;
  *)
    echo "usage: $0 {api|worker|alert|sip}" >&2
    exit 1
    ;;
esac

mkdir -p /app/snapshots /app/logs /app/models

case "$role" in
  api)
    exec python -m visionai.api
    ;;
  worker)
    exec python -m visionai.worker
    ;;
  alert|alert_worker)
    exec python -m visionai.workers.alert_worker
    ;;
  sip)
    exec python -m visionai.sip
    ;;
esac
