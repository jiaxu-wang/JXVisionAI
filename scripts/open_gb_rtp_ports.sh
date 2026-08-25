#!/bin/bash
# 放行 ZLM 国标 PS/RTP 收流口（媒体端口范围，默认 10000-10200，TCP + UDP）。
set -euo pipefail

LO="${GB_RTP_PORT_MIN:-10000}"
HI="${GB_RTP_PORT_MAX:-10200}"
NAME="JXVisionAI-GB28181-RTP"

_allow_ipt() {
  local bin="$1" proto="$2"
  command -v "$bin" >/dev/null 2>&1 || return 0
  if "$bin" -C INPUT -p "$proto" --dport "${LO}:${HI}" -j ACCEPT >/dev/null 2>&1; then
    echo "  $bin INPUT $proto ${LO}-${HI} 已存在"
    return 0
  fi
  "$bin" -I INPUT -p "$proto" --dport "${LO}:${HI}" -j ACCEPT
  echo "  $bin INPUT $proto ${LO}-${HI} 已放行"
}

if [ "$(id -u)" -ne 0 ]; then
  echo "需要 root：sudo $0"
  exit 1
fi

echo "放行国标 RTP ${LO}-${HI}/tcp+udp ..."
_allow_ipt iptables tcp
_allow_ipt iptables udp
_allow_ipt ip6tables tcp
_allow_ipt ip6tables udp

echo "当前 INPUT 策略："
iptables -S INPUT 2>/dev/null | head -20 || true

# WSL2 上摄像头走 Windows 网卡时，还要放行 Windows 防火墙
if [ -x /mnt/c/Windows/System32/netsh.exe ]; then
  echo "尝试放行 Windows 防火墙（需 Windows 管理员权限）..."
  /mnt/c/Windows/System32/netsh.exe advfirewall firewall delete rule name="${NAME}-UDP" >/dev/null 2>&1 || true
  /mnt/c/Windows/System32/netsh.exe advfirewall firewall delete rule name="${NAME}-TCP" >/dev/null 2>&1 || true
  if /mnt/c/Windows/System32/netsh.exe advfirewall firewall add rule \
      name="${NAME}-UDP" dir=in action=allow protocol=UDP localport="${LO}-${HI}"; then
    /mnt/c/Windows/System32/netsh.exe advfirewall firewall add rule \
      name="${NAME}-TCP" dir=in action=allow protocol=TCP localport="${LO}-${HI}" || true
    echo "  Windows 入站规则已添加"
  else
    echo "  Windows 防火墙未改成功（用管理员 PowerShell 再执行 scripts/open_gb_rtp_ports.ps1）"
  fi
fi

echo "完成"
