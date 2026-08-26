# Integrating the ReLIMS Print Service into a Web Application

This guide is for **any web project** (not just ReLIMS) that wants to detect the locally
installed ReLIMS Print Service and print ZPL labels through it. It is self-contained —
copy it into your project or link to it.

## What the service is

The ReLIMS Print Service is a small desktop application (Windows/Linux) that runs a local
HTTP API and bridges the browser to label printers (Zebra/Citizen — Windows spooler, CUPS,
or raw TCP/9100). Users install it once from the
[latest GitHub release](https://github.com/IT-MU-Repos/relims-print-service/releases/latest);
a system tray manager keeps it running and auto-updates it hourly.

- **Base URL**: `http://localhost:5577` (port configurable via the `api_port` config key)
- **Binding**: loopback only (`127.0.0.1`) — the browser and the service must be on the
  **same machine**. You cannot reach a user's print service from your server.
- **CORS**: allow-all (`Access-Control-Allow-Origin: *`). Any web origin may call it —
  by design, since it is loopback-bound. No authentication.
- **Mixed content**: browsers treat `http://localhost` as a *potentially trustworthy origin*,
  so pages served over `https://` may call it. Verify in your target browsers.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | **Rich health check** (v2.0.12+) — see below |
| `/status` | GET | Legacy health check (all versions, kept stable): `{"status": "ok", "version": "2.0.12", ...}` |
| `/printers` | GET | List printers: `{"printers": ["..."], "default": "..."}` |
| `/config` | GET | Current configuration (all keys) |
| `/config` | POST | Partial config update, returns updated config |
| `/print` | POST | Print one label — see [Printing](#printing) |
| `/print-batch` | POST | Print many labels in one job — see [Printing](#printing) |
| `/reset-printer` | POST | Recall factory settings + re-run media calibration (v2.0.16+). No body |
| `/logs` | GET | Last 200 log lines: `{"lines": ["..."]}` |
| `/` | GET | Built-in printer configuration UI (link users here to set up their printer) |

## The `/health` contract (v2.0.12+)

```json
{
  "service": "relims-print-service",
  "status": "ok",
  "version": "2.0.12",
  "platform": "windows",
  "backend": "network",
  "backend_available": true,
  "printer_configured": true,
  "uptime_seconds": 3641
}
```

| Key | Type | Meaning |
|-----|------|---------|
| `service` | string | Always `"relims-print-service"`. **Check this** — it proves the thing answering on the port really is this service and not another local app. |
| `status` | `"ok"` \| `"degraded"` | `"ok"` iff `backend_available && printer_configured`. |
| `version` | string | Installed service version. |
| `platform` | `"windows"` \| `"linux"` | Host platform. |
| `backend` | `"windows"` \| `"cups"` \| `"network"` | Configured printing backend. |
| `backend_available` | bool | Whether the backend's runtime is present (win32print / CUPS; always `true` for `network`). |
| `printer_configured` | bool | A printer is selected (`printer_name`, or `printer_host` for the network backend). |
| `uptime_seconds` | int | Seconds since the service process started. |

Older services (≤ 2.0.11) return **404** for `/health` — fall back to `GET /status` and
treat `{"status": "ok"}` as a healthy legacy install (see the snippet below, which does this
for you).

## Detecting the service — the three states

A browser **cannot distinguish "not installed" from "installed but not running"** — both
are a failed/refused connection. Design your UI around three states:

| State | Meaning | Suggested UI |
|-------|---------|--------------|
| `healthy` | Running, printer ready | Enable print buttons |
| `degraded` | Running, but no printer configured (or backend missing) | Warning + link to `http://localhost:5577` ("finish printer setup") |
| `unreachable` | **Not installed *or* not running** | Install CTA linking to the [latest release](https://github.com/IT-MU-Repos/relims-print-service/releases/latest) |

### Copy-paste TypeScript client

Self-contained — no dependencies:

```typescript
const PRINT_SERVICE_URL = 'http://localhost:5577';
const TIMEOUT_MS = 1500;

export interface PrintServiceHealth {
  service: string;
  status: 'ok' | 'degraded';
  version: string;
  platform: 'windows' | 'linux';
  backend: 'windows' | 'cups' | 'network';
  backend_available: boolean;
  printer_configured: boolean;
  uptime_seconds: number;
}

export interface PrintServiceHealthResult {
  state: 'healthy' | 'degraded' | 'unreachable';
  health?: PrintServiceHealth; // full /health payload (undefined when unreachable/legacy)
  version?: string;            // from /health, or /status on legacy services
  legacy?: boolean;            // true when detected via /status (service <= 2.0.11)
}

async function fetchWithTimeout(path: string): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    return await fetch(`${PRINT_SERVICE_URL}${path}`, { signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

export async function getPrintServiceHealth(): Promise<PrintServiceHealthResult> {
  try {
    const res = await fetchWithTimeout('/health');
    if (res.ok) {
      const health = (await res.json()) as PrintServiceHealth;
      // Identity check: something else may be listening on the port.
      if (health.service !== 'relims-print-service') return { state: 'unreachable' };
      return {
        state: health.status === 'ok' ? 'healthy' : 'degraded',
        health,
        version: health.version,
      };
    }
    if (res.status === 404) {
      // Service <= 2.0.11: no /health route yet. Fall back to /status.
      const legacyRes = await fetchWithTimeout('/status');
      if (legacyRes.ok) {
        const status = (await legacyRes.json()) as { status?: string; version?: string };
        if (status.status === 'ok' && typeof status.version === 'string') {
          return { state: 'healthy', version: status.version, legacy: true };
        }
      }
    }
    return { state: 'unreachable' };
  } catch {
    return { state: 'unreachable' };
  }
}
```

Usage:

```typescript
const result = await getPrintServiceHealth();
switch (result.state) {
  case 'healthy':
    // enable printing
    break;
  case 'degraded':
    // show "open http://localhost:5577 to configure your printer"
    break;
  case 'unreachable':
    // show install CTA:
    // https://github.com/IT-MU-Repos/relims-print-service/releases/latest
    break;
}
```

The short timeout matters: when the service is not installed, some environments make the
request hang instead of failing fast — never call this without an abort timeout.

## Printing

### `POST /print` — one label

Request body — at least one of `zpl` / `image` is required. When both are sent the service
picks the best format for the configured printer (ZPL preferred for ZPL-capable printers):

```json
{ "zpl": "^XA^FO50,50^A0N,40,40^FDHello^FS^XZ", "image": "<base64 PNG>", "copies": 1 }
```

Two optional flags, both honoured on Windows and Linux since v2.0.13 (`raw` was
Linux-only before that):

| Flag | Default | Effect |
| --- | --- | --- |
| `"raw": true` | `false` | Send the ZPL untouched — bypasses the service's stored label-calibration offsets (`^LH` / `^PW` rewriting) **and** its print-darkness setting (`^MD` injection). |
| `"reset_printer": true` | `false` | Before printing, send `^XA^JUF^XZ~JC` as its own job and wait ~2s: recalls the printer's factory settings and re-runs media calibration. Not saved to the printer, so a power cycle restores its own config. |

`reset_printer` is retained for compatibility but is **not used by the built-in
calibration flow any more** — printing the calibration label no longer touches the
printer. Resetting is its own explicit action: `POST /reset-printer` (no body), exposed
as **Reset Printer Settings** on the settings page. Prefer that endpoint over the flag.

Do not set `reset_printer` on ordinary label jobs — it discards any darkness or speed the
lab tuned on the front panel and adds a media feed to every print. A reset that the
printer rejects is logged and the label still prints.

**Darkness is handled by the service, not the caller.** Each workstation's
`label_darkness` config (`-30`…`30`, set on the settings page) is injected as `^MD` into
every non-`raw` label. Do not emit your own `^MD` — the service strips it before adding
its own, because Zebra treats multiple `^MD` commands in one format as cumulative. Unlike
`reset_printer`, this setting survives a printer reset, so it is the right place to fix
labels that print too faint. Note it is label-global (barcodes darken along with text) and
applies to ZPL only — image payloads are rasterized by the OS driver, which the service
does not control.

Responses: `200` `{"success": true, "copies": 1, "printer": "..."}` on success
(`printer` present for Windows/CUPS backends); `400`/`500`
`{"success": false, "error": "..."}` on failure.

```bash
curl -X POST http://localhost:5577/print \
  -H "Content-Type: application/json" \
  -d '{"zpl": "^XA^FO50,50^A0N,40,40^FDHello^FS^XZ", "copies": 1}'
```

```typescript
const res = await fetch('http://localhost:5577/print', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ zpl, copies: 1 }),
});
const result = (await res.json()) as { success: boolean; error?: string };
```

### `POST /print-batch` — many labels, one job

Sends all labels through one connection/job (much faster for network printers):

```json
{ "zpls": ["^XA...^XZ", "^XA...^XZ"], "images": ["<base64>", "..."], "copies": 1 }
```

Response: `{"success": true, "printed": 2, "total": 2}` (plus `"error"` on failure).

## Versioning and updates

- Installed clients auto-update **hourly** from
  [GitHub Releases](https://github.com/IT-MU-Repos/relims-print-service/releases); users can
  also update on demand from the system tray ("Check for Updates").
- Code against `/health`, but keep the `/status` 404-fallback (as in the snippet) so users
  who haven't yet updated past 2.0.11 are still detected.
- To show a download link or "latest version" badge in your app, query the public releases
  API from the browser and use the assets' `browser_download_url`:

```typescript
const res = await fetch(
  'https://api.github.com/repos/IT-MU-Repos/relims-print-service/releases/latest',
  { headers: { Accept: 'application/vnd.github+json' } }
);
const release = (await res.json()) as {
  tag_name: string;
  assets: { name: string; browser_download_url: string }[];
};
// Windows installer: relims-print-manager-setup.exe
// Linux:             relims-print-service-linux.tar.gz, relims-print-manager-linux-install.sh
```

## Troubleshooting integration

| Symptom | Cause / fix |
|---------|-------------|
| Always `unreachable` even though installed | Service stopped (tray → Start Service), or `api_port` changed from 5577 |
| `/health` 404 but `/status` works | Service ≤ 2.0.11 — the fallback handles it; the client auto-updates within an hour of a new release |
| `unreachable` with wrong `service` value | Another app is on port 5577 — user should change `api_port` (config UI) |
| Requests hang | You forgot the abort timeout |
| `degraded` | Service is fine — the user just hasn't configured a printer at `http://localhost:5577` |
