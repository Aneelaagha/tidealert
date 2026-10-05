# Offline mode

Offline mode is a **connection state** that sits above everything the page shows. It does not recompute, estimate or
fill in anything in the browser. When the TideAlert server can't be reached, the page keeps what it last loaded and
says so.

## What it does

- **Detects** loss of the server by a request failing at the network level (connection refused, DNS, or no reply
  within the timeout), by the browser's `online`/`offline` events, and by a probe of `/copilot/status` every 5 s.
  An HTTP error status (4xx, 5xx) is a server error, not offline, and never triggers it.
- **Confirms** before declaring it: the first failure moves the page to *checking*; a second failed probe moves it
  to *offline*. "Offline since" is the time of the first failure.
- **Keeps the last view on screen.** Each request's last response for the current run and slider time is held in
  memory and served when the same request fails at the network level.
- **Says so.** A banner above the page shows "Offline since HH:MM" and when the view was loaded. The status line
  reads "cached" instead of a load time.
- **Recovers.** Any HTTP response returns the page to online and the view is read again from the server.

## Source freshness while offline

`/map/freshness` is not extended with a new status. While offline:

| Run mode | A source reads |
|---|---|
| live | **unknown** ("offline since HH:MM"). A live source's status can't be known without the server. |
| replay, scenario | its load-time status, labelled **cached** (the data is historical; nothing new arrives). |

If freshness was never loaded, the banner says "not loaded before the connection dropped".

## What does not work offline, on purpose

- **Copilot questions and task actions** are never queued or replayed. They fail with a message saying nothing was
  sent. A queued action could be applied later against a view that has moved on.
- **A request not loaded before the outage** (a different run, a different slider time, a zone not yet opened) fails
  with an offline message. Only one view is cached (the run and time on screen), so moving the slider offline shows
  that the new view isn't available rather than a nearest guess.
- **Reloading the page offline** is not supported: the cache is in memory only (no service worker, no IndexedDB).

## Limits of the tests

The tests cover the state machine, the cache rules, the freshness labels, and the API layer with a mocked `fetch`
(network failure serves the cache; an HTTP 500 doesn't; a POST is never sent offline). They do not exercise a real
network drop; that is checked by hand in a browser by stopping the backend.

Two guards in `frontend/src/test/no-invented-data.test.ts` were widened for this: `fetch` may also appear in
`lib/connection.ts` (the timeout wrapper and probe), and the wall clock may be read in `App.tsx`, `lib/api.ts` and
`lib/connection.ts`, only for connection times the browser itself observed.

## Where it lives

`frontend/src/lib/connection.ts` (state machine, probe, cache), `lib/useConnection.ts`, `lib/api.ts` (`get`/`post`
go through it), `components/ConnectionBanner.tsx`, `components/FreshnessBanner.tsx`.
