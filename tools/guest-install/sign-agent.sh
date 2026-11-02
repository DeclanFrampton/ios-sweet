#!/bin/sh
# A local development signature for the isolated guest agent, not Apple trust.
set -eu
mkdir -p /tmp/iossweet-sign-agent
cp /work/iossweet-agent /tmp/iossweet-sign-agent/iossweet-agent
/usr/local/bin/rcodesign sign --timestamp-url none \
  --binary-identifier org.iossweet.development-agent \
  --entitlements-xml-file /scripts/agent-entitlements.plist \
  /tmp/iossweet-sign-agent/iossweet-agent
cp /tmp/iossweet-sign-agent/iossweet-agent /work/iossweet-agent
echo DEVELOPMENT_AGENT_SIGNED_WITH_EXPLICIT_APP_MANAGEMENT_ENTITLEMENTS
