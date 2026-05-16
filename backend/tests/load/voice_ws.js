// k6 soak test — 50 concurrent WebSocket connections to /voice/stream/{call_id}
// held open for 5 minutes.
//
// The route lives under `app/websockets/voice_bridge.py` as
// `/voice/stream/{call_id}` (no `/ws` prefix in the app — but external load
// balancers usually mount it at `/ws/voice/*`; override `WS_PATH_TEMPLATE` if
// your edge differs).
//
// Authentication: the bridge accepts a short-lived ticket JWT issued by
// `POST /api/v1/auth/ws-ticket`. Set `WS_TICKET` before the run.
//
// Run:
//   BASE_URL=https://staging.thetribunal.app \
//   WS_TICKET=<jwt> \
//   k6 run backend/tests/load/voice_ws.js

import ws from 'k6/ws';
import { check, sleep } from 'k6';
import { Counter, Trend } from 'k6/metrics';
import { WS_BASE_URL } from './lib/common.js';

const wsConnectErrors = new Counter('ws_connect_errors');
const wsHoldDuration = new Trend('ws_hold_duration_ms', true);

const WS_PATH_TEMPLATE = __ENV.WS_PATH_TEMPLATE || '/voice/stream/{call_id}';
const WS_TICKET = __ENV.WS_TICKET || '';
const HOLD_SECONDS = Number(__ENV.HOLD_SECONDS || 300); // 5 minutes
const CONCURRENT = Number(__ENV.CONCURRENT || 50);

export const options = {
  scenarios: {
    soak_50_concurrent: {
      executor: 'per-vu-iterations',
      vus: CONCURRENT,
      iterations: 1,
      // 5min hold + slack for connect/teardown.
      maxDuration: `${HOLD_SECONDS + 60}s`,
    },
  },
  thresholds: {
    ws_connect_errors: ['count<5'],
    ws_session_duration: [`p(95)>${(HOLD_SECONDS - 10) * 1000}`],
  },
};

function buildUrl() {
  const callId = `k6-${__VU}-${Date.now()}`;
  const path = WS_PATH_TEMPLATE.replace('{call_id}', encodeURIComponent(callId));
  const sep = path.includes('?') ? '&' : '?';
  const qs = WS_TICKET ? `${sep}ticket=${encodeURIComponent(WS_TICKET)}` : '';
  return `${WS_BASE_URL}${path}${qs}`;
}

export default function () {
  const url = buildUrl();
  const start = Date.now();

  const res = ws.connect(url, {}, (socket) => {
    socket.on('open', () => {
      // Send a Telnyx-style media-start frame so the bridge enters the
      // streaming state machine (otherwise it may close us out).
      socket.send(
        JSON.stringify({
          event: 'start',
          start: {
            stream_id: `k6-stream-${__VU}`,
            call_control_id: `k6-${__VU}`,
            media_format: { encoding: 'PCMU', sample_rate: 8000, channels: 1 },
          },
        }),
      );

      // Keepalive: send a tiny silence frame every 5s to look like a real
      // media stream and avoid idle-timeout closes.
      socket.setInterval(() => {
        socket.send(
          JSON.stringify({
            event: 'media',
            media: {
              track: 'inbound',
              chunk: '1',
              timestamp: String(Date.now()),
              payload: 'AAAA', // 3 bytes of silence, base64
            },
          }),
        );
      }, 5000);
    });

    socket.on('error', (e) => {
      wsConnectErrors.add(1);
      console.error(`ws error vu=${__VU}: ${e?.error?.() ?? e}`);
    });

    socket.setTimeout(() => {
      wsHoldDuration.add(Date.now() - start);
      socket.close();
    }, HOLD_SECONDS * 1000);
  });

  const ok = check(res, {
    'ws handshake 101': (r) => r && r.status === 101,
  });
  if (!ok) wsConnectErrors.add(1);
  sleep(1);
}
