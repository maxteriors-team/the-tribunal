// k6 load test — POST /webhooks/telnyx/sms at 100 RPS for 60s.
//
// Target staging MUST have `SKIP_WEBHOOK_VERIFICATION=true` (see
// app/core/webhook_security.py) because k6's stdlib does not expose ed25519
// signing. The script still sends Telnyx-shaped signature headers so the
// dispatch path matches production.
//
// Run:
//   BASE_URL=https://staging.thetribunal.app \
//   k6 run backend/tests/load/telnyx_webhook.js

import http from 'k6/http';
import { check } from 'k6';
import { BASE_URL, telnyxSignedHeaders, randomPhone } from './lib/common.js';

export const options = {
  scenarios: {
    sustained_100rps: {
      executor: 'constant-arrival-rate',
      rate: 100,
      timeUnit: '1s',
      duration: '60s',
      preAllocatedVUs: 50,
      maxVUs: 200,
    },
  },
  thresholds: {
    // Webhook ingestion must stay snappy even under sustained load —
    // Telnyx retries after a few seconds.
    http_req_duration: ['p(95)<500', 'p(99)<1500'],
    http_req_failed: ['rate<0.01'],
    checks: ['rate>0.99'],
  },
};

function buildInboundSmsPayload() {
  const from = randomPhone();
  const to = randomPhone();
  return {
    data: {
      event_type: 'message.received',
      id: `evt_${Date.now()}_${Math.random().toString(36).slice(2)}`,
      occurred_at: new Date().toISOString(),
      payload: {
        id: `msg_${Math.random().toString(36).slice(2)}`,
        from: { phone_number: from },
        to: [{ phone_number: to }],
        text: 'load test inbound message',
        direction: 'inbound',
        type: 'SMS',
      },
    },
  };
}

export default function () {
  const body = JSON.stringify(buildInboundSmsPayload());
  const res = http.post(`${BASE_URL}/webhooks/telnyx/sms`, body, {
    headers: telnyxSignedHeaders(),
    tags: { endpoint: 'telnyx_sms' },
  });

  check(res, {
    'status is 2xx': (r) => r.status >= 200 && r.status < 300,
    'has ok body': (r) => r.body && r.body.includes('ok'),
  });
}
