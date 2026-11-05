#!/bin/zsh
# Install (or reinstall) the nightly batch and the always-on review gate.
set -e
D=~/Library/LaunchAgents; mkdir -p "$D" ~/Developer/outreach-platform/logs
for name in com.outreach.nightly com.outreach.review; do
  cp ~/Developer/outreach-platform/ops/$name.plist "$D/"
  launchctl bootout gui/$(id -u)/$name 2>/dev/null || true
  launchctl bootstrap gui/$(id -u) "$D/$name.plist"
done
launchctl print gui/$(id -u)/com.outreach.nightly | grep -E "state|next" || true
echo "installed: nightly batch at 02:00 (retries 04:00, 06:00), review gate on http://127.0.0.1:8000"
