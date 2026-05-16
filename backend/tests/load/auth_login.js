// k6 load test — POST /api/v1/auth/login at a sustained 10 RPS for 60s.
//
// The login endpoint rate-limits the same client IP at 10 attempts per
// 15-minute window (`_AUTH_RATE_LIMIT` in app/api/v1/auth.py), so this script
// EXPECTS the response distribution to be dominated by 429s after the first
// ~10 requests per VU-source-IP. The check below treats either 401 (wrong
// password) or 429 (rate-limited) as "endpoint correctly responded" — the
// goal is to verify the rate limiter holds, not to authenticate.
//
// Run:
//   BASE_URL=https://staging.thetribunal.app k6 run backend/tests/load/auth_login.js

import http from 'k6/http';
import { check } from 'k6';
import { Rate } from 'k6/metrics';
import { BASE_URL } from './lib/common.js';

const rateLimited = new Rate('rate_limited_429');

export const options = {
  scenarios: {
    sustained_10rps: {
      executor: 'constant-arrival-rate',
      rate: 10,
      timeUnit: '1s',
      duration: '60s',
      preAllocatedVUs: 10,
      maxVUs: 30,
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<800'],
    // Past minute one, the rate limiter must be active — we expect >50%
    // of responses to be 429s. If this drops, the limiter is leaking.
    rate_limited_429: ['rate>0.5'],
    checks: ['rate>0.99'],
  },
};

export default function () {
  // OAuth2PasswordRequestForm — application/x-www-form-urlencoded.
  const body = {
    username: `load+${__VU}@example.com`,
    password: 'definitely-wrong-password',
  };
  const res = http.post(`${BASE_URL}/api/v1/auth/login`, body, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    tags: { endpoint: 'auth_login' },
  });

  rateLimited.add(res.status === 429);

  check(res, {
    'status is 401 or 429': (r) => r.status === 401 || r.status === 429,
    'no 5xx': (r) => r.status < 500,
  });
}
