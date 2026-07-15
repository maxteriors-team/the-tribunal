// k6 load test — POST /webhooks/calcom/booking at 50 RPS for 60s.
//
// Generates a real HMAC-SHA256 signature over the raw body so the
// `verify_calcom_webhook` check in app/core/webhook_security.py passes.
//
// Run:
//   BASE_URL=https://staging.thetribunal.app \
//   CALCOM_WEBHOOK_SECRET=<secret> \
//   k6 run backend/tests/load/calcom_webhook.js

import http from 'k6/http';
import { check } from 'k6';
import { BASE_URL, calcomSignedHeaders } from './lib/common.js';

export const options = {
  scenarios: {
    sustained_50rps: {
      executor: 'constant-arrival-rate',
      rate: 50,
      timeUnit: '1s',
      duration: '60s',
      preAllocatedVUs: 25,
      maxVUs: 100,
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<500', 'p(99)<2000'],
    http_req_failed: ['rate<0.01'],
    checks: ['rate>0.99'],
  },
};

function buildBookingCreatedPayload() {
  // Distinct uid per request → idempotency dedupe never trips.
  const uid = `bk_${Date.now()}_${Math.random().toString(36).slice(2)}`;
  const start = new Date(Date.now() + 24 * 3600 * 1000).toISOString();
  const end = new Date(Date.now() + 24.5 * 3600 * 1000).toISOString();
  return {
    triggerEvent: 'BOOKING_CREATED',
    trigger: 'BOOKING_CREATED',
    createdAt: new Date().toISOString(),
    payload: {
      uid,
      title: 'k6 load test booking',
      startTime: start,
      endTime: end,
      attendees: [
        {
          name: 'Load Tester',
          email: `load+${uid}@example.com`,
          timeZone: 'America/New_York',
        },
      ],
      organizer: {
        name: 'Homeowner',
        email: 'homeowner@example.com',
        timeZone: 'America/New_York',
      },
    },
    data: {
      uid,
      title: 'k6 load test booking',
      startTime: start,
      endTime: end,
    },
  };
}

export default function () {
  const body = JSON.stringify(buildBookingCreatedPayload());
  const res = http.post(`${BASE_URL}/webhooks/calcom/booking`, body, {
    headers: calcomSignedHeaders(body),
    tags: { endpoint: 'calcom_booking' },
  });

  check(res, {
    'status is 2xx': (r) => r.status >= 200 && r.status < 300,
    'has ok body': (r) => r.body && r.body.includes('ok'),
  });
}
