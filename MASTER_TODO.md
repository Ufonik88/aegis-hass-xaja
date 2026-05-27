# MASTER TODO — Video Functionality for Aegis for Ajax

> **Last Updated:** 2026-05-26
> **Status:** Phase 1 Complete / Phase 2 Complete / Phase 3 Complete / Phase 4 Complete (5.2 Two-Way Audio deferred)

This document is the **single source of truth** for all video-related work in this fork of
[Aegis for Ajax](https://github.com/bvis/aegis-hass). It tracks:
- What has been implemented and how
- What remains to be built
- Known limitations and open questions
- Required external information from Ajax Systems
- File-by-file change history

---

## Table of Contents

1. [Project Context](#1-project-context)
2. [Phase 1 — Foundation (COMPLETE)](#2-phase-1--foundation-complete)
   - [2.1 New File: `api/video.py`](#21-new-file-apivideopy)
   - [2.2 Modified: `camera.py`](#22-modified-camerapy)
   - [2.3 Modified: `coordinator.py`](#23-modified-coordinatorpy)
   - [2.4 Modified: `api/__init__.py`](#24-modified-api__init__py)
   - [2.5 Modified: `tests/unit/test_camera.py`](#25-modified-testsunittest_camerapy)
3. [Phase 2 — Snapshot/Preview Images (COMPLETE)](#3-phase-2--snapshotpreview-images-complete)
4. [Phase 3 — WebRTC Live Streaming (COMPLETE)](#4-phase-3--webrtc-live-streaming-complete)
5. [Phase 4 — Advanced Features (PLANNED)](#5-phase-4--advanced-features-planned)
6. [Known Limitations & Open Questions](#6-known-limitations--open-questions)
7. [Required External Information](#7-required-external-information)
8. [File Change Log](#8-file-change-log)
9. [Test Status](#9-test-status)

---

## 1. Project Context

### What Is Aegis for Ajax?

A third-party Home Assistant custom integration for Ajax Security Systems. It communicates
with Ajax cloud servers using the **same gRPC protocol** as the official Ajax mobile app.
No Enterprise API key is required — regular account credentials (email + password) are sufficient.

### Communication Architecture

| Channel | Protocol | Transport | Purpose |
|---------|----------|-----------|---------|
| gRPC | Protobuf | TLS to `mobile-gw.prod.ajax.systems:443` | Device state, arm/disarm, photo capture, video settings |
| HTS | Proprietary binary | TCP+TLS to `hts.prod.ajax.systems:443` | Hub network state, electrical readings |
| FCM Push | Firebase Cloud Messaging | `mtalk.google.com:5228` | Security events, photo URLs, doorbell rings |

### Current Platforms (12 total)

Alarm Control Panel, Binary Sensor, Button, **Camera**, Event, Sensor, Switch, Light, Lock,
Update, Valve.

### How Protos Were Obtained

All `.proto` files in `proto_src/` were reverse-engineered from the Ajax Android APK.
The `custom_components/aegis_ajax/proto/` directory contains compiled `_pb2.py` /
`_pb2_grpc.py` / `_pb2.pyi` files. The video API proto surface is **extensive** (~70+
video-related proto files) but had zero runtime integration code before Phase 1.

---

## 2. Phase 1 — Foundation (COMPLETE)

**Goal:** Make `video_edge_*` devices appear as camera entities, enable stream URL
resolution via gRPC, and wire up HA's `Stream` component for RTSP-based video.

**Status:** All code written. All tests pass (1399 unit tests). Ready for real-device testing.

### 2.1 New File: `api/video.py`

`custom_components/aegis_ajax/api/video.py` — 152 lines

**Class: `VideoApi(client: AjaxGrpcClient)`**

Three methods that call Ajax gRPC video endpoints using the compiled protobuf stubs.

#### Method: `get_surveillance_camera_stream_url(hub_hex_id, camera_hex_id) -> str | None`

| Detail | Value |
|--------|-------|
| **gRPC Service** | `systems.ajax.mobile.v2.service.hub.company.media.SurveillanceCamerasService` |
| **gRPC Method** | `getStreamSettings` |
| **Proto Request** | `GetStreamSettingsRequest(hub_hex_id, camera_hex_id)` |
| **Proto Response** | `GetStreamSettingsResponse` with `success.stream_settings` |
| **Returns** | `SurveillanceCameraStreamSettings.stream_data_url` (RTSP URL) when `service_type == 1` (RTSP_STREAM) |
| **Timeout** | 10 seconds |

This is the **only endpoint in Ajax's API that returns a raw RTSP URL**. It applies to
legacy hub-connected surveillance cameras (not VideoEdge devices).

#### Method: `get_onvif_and_rtsp_settings(space_id, video_edge_id) -> tuple[int|None, int|None, list[str]|None]`

| Detail | Value |
|--------|-------|
| **gRPC Service** | `systems.ajax.api.ecosystem.v3.mobilegwsvc.service.get_video_edge_onvif_and_rtsp_settings.GetVideoEdgeOnvifAndRtspSettingsService` |
| **gRPC Method** | `execute` |
| **Proto Request** | `GetVideoEdgeOnvifAndRtspSettingsRequest(space_id, video_edge_id)` |
| **Proto Response** | `GetVideoEdgeOnvifAndRtspSettingsResponse` with `success.onvif_settings` and `success.rtsp_settings` |
| **Returns** | `(onvif_http_port, rtsp_http_port, [onvif_usernames])` |
| **Timeout** | 10 seconds |

The ONVIF `http_port` and RTSP `http_port` are `int32` values. **No RTSP URL string is
returned** — only the port number. The URL must be constructed heuristically using the
device ID as a host (see Known Limitations).

#### Method: `get_video_player_channels(space_id) -> list[dict]`

| Detail | Value |
|--------|-------|
| **gRPC Service** | `systems.ajax.api.ecosystem.v3.mobilegwsvc.service.stream_video_player.StreamVideoPlayerService` |
| **gRPC Method** | `execute` (server-streaming) |
| **Proto Request** | `StreamVideoPlayerRequest(space_id)` |
| **Proto Response** | `StreamVideoPlayerResponse` with `success.initial_state.video_edges[]` or `success.updates.video_edges[]` |
| **Returns** | List of `{"video_edge_id": str, "channel_id": str}` dicts |
| **Timeout** | 15 seconds |

Used as a building block for future preview/snapshot URL retrieval. Currently unused
by any entity — the data is available for subsequent phases.

---

### 2.2 Modified: `camera.py`

`custom_components/aegis_ajax/camera.py` — 214 lines (was 133 lines)

#### New Device Type Sets

```python
CAMERA_DEVICE_TYPES = {
    # Existing motion camera types (unchanged)
    "motion_cam", "motion_cam_outdoor", "motion_cam_fibra",
    "motion_cam_phod", "motion_cam_outdoor_phod", "motion_cam_fibra_base",
    # NEW: video edge device types (previously invisible to camera platform)
    "video_edge_doorbell", "video_edge_turret", "video_edge_bullet",
    "video_edge_minidome", "video_edge_indoor", "video_edge_unknown",
}

_VIDEO_EDGE_TYPES = {
    "video_edge_doorbell", "video_edge_turret", "video_edge_bullet",
    "video_edge_minidome", "video_edge_indoor", "video_edge_unknown",
}

_MOTION_CAM_TYPES = {
    "motion_cam", "motion_cam_outdoor", "motion_cam_fibra",
}
```

#### New Properties & Methods

| Member | Type | Purpose |
|--------|------|---------|
| `_stream_url: str \| None` | attribute | Cached stream URL, set once on first resolution |
| `_stream_url_resolved: bool` | attribute | Guard flag — prevents redundant gRPC calls |
| `motion_detection_enabled` | property | `True` for video edge types (native motion), `False` for motion cams (photo-only) |
| `stream_source()` | async method | HA's entry point for video streaming. Lazily resolves RTSP URL via VideoApi, caches result |
| `_resolve_hub_camera_stream()` | async method | Calls `video_api.get_surveillance_camera_stream_url()` for legacy hub cameras |
| `_resolve_video_edge_stream()` | async method | Calls `video_api.get_onvif_and_rtsp_settings()` and constructs `rtsp://{device_id}:{port}/stream` |
| `supported_features` | property | Returns `Camera.EntityFeature.STREAM` (enables HA Stream component) |

#### Stream URL Resolution Logic

```
stream_source() is called by HA
  ↓
  ├─ Already resolved? → return cached _stream_url
  ├─ Device offline/missing? → return None
  ├─ Device type in _MOTION_CAM_TYPES?
  │   → call _resolve_hub_camera_stream()
  │       → video_api.get_surveillance_camera_stream_url(hub_id, device_id)
  │           → Returns raw RTSP URL (e.g. "rtsp://192.168.1.x:554/...")
  └─ Device type in _VIDEO_EDGE_TYPES?
      → call _resolve_video_edge_stream()
          → video_api.get_onvif_and_rtsp_settings(space_id, device_id)
              → If rtsp_port: return "rtsp://{device_id}:{rtsp_port}/stream"
              → If no port: return None
```

---

### 2.3 Modified: `coordinator.py`

`custom_components/aegis_ajax/coordinator.py` — 930 lines (was 924 lines)

#### New Import

```python
from custom_components.aegis_ajax.api.video import VideoApi  # line 30
```

#### New Initialization (in `__init__`)

```python
self._video_api = VideoApi(client)  # line 124
```

#### New Property

```python
@property
def video_api(self) -> VideoApi:        # lines 203-205
    return self._video_api
```

---

### 2.4 Modified: `api/__init__.py`

`custom_components/aegis_ajax/api/__init__.py` — 38 lines (was 34 lines)

#### New Import

```python
from custom_components.aegis_ajax.api.video import VideoApi  # line 20
```

#### Updated `__all__`

Added `"VideoApi"` to the exported symbols list.

---

### 2.5 Modified: `tests/unit/test_camera.py`

`tests/unit/test_camera.py` — 160 new lines (332 → 492)

#### New Test Methods (15 tests added)

**Device type tests (class `TestCameraDeviceTypes`):**
| Test | What It Verifies |
|------|-----------------|
| `test_video_edge_doorbell_is_camera` | Doorbell in CAMERA_DEVICE_TYPES |
| `test_video_edge_turret_is_camera` | TurretCam in CAMERA_DEVICE_TYPES |
| `test_video_edge_bullet_is_camera` | BulletCam in CAMERA_DEVICE_TYPES |
| `test_video_edge_minidome_is_camera` | MiniDome in CAMERA_DEVICE_TYPES |
| `test_video_edge_indoor_is_camera` | Indoor Cam in CAMERA_DEVICE_TYPES |

**PhOD type tests (class `TestPhodDeviceTypes`):**
| Test | What It Verifies |
|------|-----------------|
| `test_video_edge_not_phod` | Video edge types NOT in PHOD_DEVICE_TYPES |

**Entity behavior tests (class `TestAjaxCamera`):**
| Test | What It Verifies |
|------|-----------------|
| `test_motion_cam_has_motion_detection_disabled` | Motion cams → `motion_detection_enabled = False` |
| `test_video_edge_has_motion_detection_enabled` | Video edge → `motion_detection_enabled = True` |
| `test_supported_features_includes_stream` | `supported_features == Camera.EntityFeature.STREAM` |
| `test_stream_source_hub_camera_rtsp` | Hub camera → RTSP URL resolved via VideoApi |
| `test_stream_source_hub_camera_no_url` | Hub camera → None when API returns no URL |
| `test_stream_source_video_edge_rtsp` | Video edge → constructs `rtsp://{id}:{port}/stream` |
| `test_stream_source_video_edge_no_rtsp_port` | Video edge → None when no RTSP port |
| `test_stream_source_device_missing` | Missing device → None |
| `test_stream_source_cached` | Second call returns cached URL, no duplicate gRPC call |

---

## 3. Phase 2 — Snapshot/Preview Images (COMPLETE)

**Status:** All code written. All tests pass. Ready for real-device testing.

### Implementation Summary

Phase 2 surfaces preview/snapshot images from Ajax's VideoEdge `Channel.channel_preview.image_url`
in the HA camera entity. The endpoint used is `VideoEdgeService/streamUpdates` — a server-streaming
call that returns full `VideoEdge` objects with `Channel` data including the `ChannelPreview`
message (`image_url` + `created_at`).

#### How It Works

1. **`VideoApi.get_channel_preview_urls(space_id)`** opens a short-lived stream to
   `VideoEdgeService/streamUpdates`, captures the `InitialState` snapshot, extracts
   `channel_preview.image_url` for each channel, and returns `{channel_id: image_url}`.
2. **`_maybe_refresh_preview_urls(now)`** — new coordinator method called every 120 seconds
   from `_async_update_data`. Iterates all spaces and merges results into
   `coordinator.video_preview_urls`.
3. **`AjaxCamera.async_camera_image()`** checks `coordinator.video_preview_urls` as a
   fallback AFTER photo-on-demand URLs and BEFORE persisted photos from disk.
4. **`_download_preview(url)`** — new method similar to `_download_image()` but with a
   more permissive URL validator (`_is_valid_preview_url()`) since Ajax preview images
   may be served from internal/edge CDN domains.

#### Priority chain in `async_camera_image()`
```
1. last_photo_urls (button-triggered Photo on Demand)
2. video_preview_urls (periodically refreshed channel preview snapshots)   ← NEW
3. _get_last_image() (persisted photo from disk)
```

### Tasks

- [x] **3.1** Call `VideoEdgeService/streamUpdates` at coordinator intervals to populate
  `video_preview_urls` dict (keyed by channel/device_id)
- [x] **3.2** Update `async_camera_image()` to check `video_preview_urls` as fallback
- [x] **3.3** Add periodic refresh of preview URLs (120-second interval)
- [x] **3.4** Add `_is_valid_preview_url()` — accepts http/https with any valid hostname
- [x] **3.5** Write unit tests — 9 new tests for preview image retrieval, caching, URL
  validation, download error handling, and priority chain
- [ ] **3.6** Test with real hardware (Doorbell, Indoor Cam, etc.)

### Files Modified

| File | Lines Changed | Description |
|------|--------------|-------------|
| `api/video.py` | 152 → 204 (+52) | New method `get_channel_preview_urls()`, new proto imports for `SpaceLocator` and `StreamVideoEdgeUpdatesRequest/Response` |
| `coordinator.py` | 930 → 995 (+65) | New `video_preview_urls` dict, `_preview_urls_last_fetch` timestamp, `_maybe_refresh_preview_urls()` method, wired into `_async_update_data` |
| `camera.py` | 214 → 240 (+26) | Preview URL fallback in `async_camera_image()`, new `_download_preview()` and `_is_valid_preview_url()` methods |
| `tests/unit/test_camera.py` | 526 → 695 (+169) | 9 new tests for preview image flow |

### Test Coverage (Phase 2 additions)

| Test | What It Verifies |
|------|-----------------|
| `test_async_camera_image_uses_preview_url_fallback` | Downloads preview when `video_preview_urls` has a URL |
| `test_async_camera_image_preview_skip_on_bad_url` | Skips preview for non-http/https URLs |
| `test_async_camera_image_preview_handles_download_error` | Falls back to cached image on download error |
| `test_async_camera_image_preview_overrides_last_image` | Fresh preview replaces old `_last_image` |
| `test_async_camera_image_photo_takes_priority_over_preview` | Photo-on-demand URL wins over preview URL |
| `test_is_valid_preview_url_accepts_https` | `_is_valid_preview_url()` accepts https |
| `test_is_valid_preview_url_accepts_http` | `_is_valid_preview_url()` accepts http |
| `test_is_valid_preview_url_rejects_ftp` | `_is_valid_preview_url()` rejects ftp |
| `test_is_valid_preview_url_rejects_empty` | `_is_valid_preview_url()` rejects malformed input |

### Notes

- The `VideoEdgeService/streamUpdates` endpoint returns the **full** `VideoEdge` proto with
  `Channel` data including `channel_preview.image_url`. This is different from the lighter
  `StreamVideoPlayerService` used in Phase 1.
- Preview URLs are refreshed every 120 seconds. The stream is opened, the `InitialState`
  is captured, and the stream is immediately closed (no persistent connection).
- `_is_valid_preview_url()` accepts any http/https URL with a valid hostname. This is
  intentionally more permissive than `_is_valid_photo_url()` because Ajax preview images
  may be served from edge CDN or internal domains not matching `*.ajax.systems`.

---

## 4. Phase 3 — WebRTC Live Streaming (COMPLETE)

**Status:** All code written. All tests pass (1416 unit tests). Ready for real-device testing.

### Goal
Implement live video streaming via Ajax's native WebRTC protocol using Home Assistant's
built-in `Camera.async_handle_async_webrtc_offer()` API. HA's frontend creates the WebRTC
peer connection, sends the offer SDP to the backend, and the integration proxies the
signaling to/from Ajax's cloud WebRTC gateway.

### Key Decision: v3 `StreamWebrtcService/execute` over v2 `WebrtcService`

Although the original plan targeted the v2 `WebrtcService` (unary/stream methods), the
v3 `StreamWebrtcService/execute` bidirectional stream is a much better fit for HA's
offer/answer model:

| Aspect | v2 `WebrtcService` | v3 `StreamWebrtcService/execute` |
|--------|-------------------|---------------------------------|
| Initiate | `initiate` (server-streaming) | `Init` message on bidi stream |
| Offer/Answer | Separate `sendOffer` RPC | In-stream `Offer`/`Answer` messages |
| ICE candidates | Separate `suggestNewIceCandidate` RPC | In-stream `NewIceCandidate` messages |
| Session lifecycle | Multiple independent RPCs | Single persistent bidirectional stream |

The bidirectional stream lets us send HA's offer and immediately read Ajax's answer on
the same connection, which is exactly what `async_handle_async_webrtc_offer` needs.

### Implementation Summary

#### 4.1 `api/client.py` — New `call_bidi_stream()` method

Added `AjaxGrpcClient.call_bidi_stream(method_path, response_type, timeout)` which opens
a `grpc.aio.stream_stream` RPC and returns a `StreamStreamCall` object supporting
manual `write()` / `read()` for bidirectional request/response exchange.

#### 4.2 `api/video.py` — WebRTC signaling methods

**New proto imports:** `v3/mobilegwsvc/service/stream_webrtc` (request/response/endpoint)
and common WebRTC types (`Stream`, `SessionDescription`, `IceCandidate`, `FrameTypeId`,
`StreamType`).

**`initiate_webrtc(space_id, video_edge_id, channel_id, offer_sdp)`**
- Opens bidirectional stream to `StreamWebrtcService/execute`
- Sends `Init` with `SpaceLocator`, `video_edge_id`, one `Stream` (main stream,
  video + audio, live mode)
- Reads `Init` response → extracts `webrtc_session_id` and ICE servers
- Sends `Offer` with HA's offer SDP
- Reads `Answer` response → returns `(session_id, answer_sdp, call_object)`

**`send_webrtc_candidate(call, candidate_dict)`**
- Writes a `NewIceCandidate` message to the active bidirectional stream
- Maps HA candidate dict keys (`sdpMid`, `sdpMLineIndex`, `candidate`) to Ajax's
  `IceCandidate` proto fields

**`close_webrtc_call(call)`**
- Cancels the active `StreamStreamCall` to cleanly terminate the stream

#### 4.3 `camera.py` — HA WebRTC camera entity methods

**`async_handle_async_webrtc_offer(offer_sdp, session_id, send_message)`**
1. Validates device is a `_VIDEO_EDGE_TYPE` and resolves its space
2. Calls `video_api.initiate_webrtc()` to get Ajax's answer SDP
3. Sends `WebRTCAnswer(answer_sdp)` back to HA via `send_message`
4. Stores the active `call` object in `self._webrtc_sessions[session_id]`
5. Starts an `asyncio.Task` running `_read_webrtc_ice_candidates()` to forward
   ICE candidates from Ajax → HA

**`async_on_webrtc_candidate(session_id, candidate)`**
- Looks up the active session's `call` object
- Converts HA's `RTCIceCandidateInit` to a dict and calls `video_api.send_webrtc_candidate()`

**`_read_webrtc_ice_candidates(session_id, call, send_message)`**
- Background loop reading `StreamWebrtcResponse` messages from the Ajax stream
- When `new_ice_candidate` is received, constructs `RTCIceCandidateInit` and sends
  `WebRTCCandidate` to HA via `send_message`
- Exits on stream close or error; cleans up session state

**`close_webrtc_session(session_id)`**
- Called by HA when the user stops viewing the stream
- Cancels the reader task, removes session state, closes the gRPC call

### WebRTC Signaling Flow

```
HA Frontend                      HA Backend (AjaxCamera)           Ajax Cloud
    |                                    |                              |
    |-- create peer connection -------->|                              |
    |<-- generate local offer SDP ------|                              |
    |-- websocket: offer ---------------->|                             |
    |                                    |-- Init ->                    |
    |                                    |<-- Init (session_id, ICE) ---|
    |                                    |-- Offer (HA offer) ->        |
    |                                    |<-- Answer (Ajax answer) -----|
    |<-- websocket: WebRTCAnswer --------|                             |
    |                                    |                              |
    |-- ICE candidate ------------------->|                             |
    |                                    |-- NewIceCandidate ->         |
    |<-- ICE candidate -------------------|<-- NewIceCandidate ---------|
    |                                    |                              |
    |  <==== DIRECT PEER-TO-PEER MEDIA (video/audio) ====>             |
```

### Tasks

- [x] **4.1** Add `call_bidi_stream()` to `AjaxGrpcClient` for bidirectional gRPC streaming
- [x] **4.2** Implement `VideoApi.initiate_webrtc()` using v3 `StreamWebrtcService/execute`
- [x] **4.3** Implement `VideoApi.send_webrtc_candidate()` for ICE candidate forwarding
- [x] **4.4** Implement `VideoApi.close_webrtc_call()` for session teardown
- [x] **4.5** Override `Camera.async_handle_async_webrtc_offer()` in `AjaxCamera`
- [x] **4.6** Override `Camera.async_on_webrtc_candidate()` in `AjaxCamera`
- [x] **4.7** Add `close_webrtc_session()` and `_read_webrtc_ice_candidates()` background reader
- [x] **4.8** Support main/sub stream selection (`ST_MAIN` with video+audio `FrameTypeId` filters)
- [x] **4.9** Write unit tests — 8 new tests for WebRTC offer/answer, candidate forwarding,
  session cleanup, error paths, and device-type guards
- [ ] **4.10** Test with real hardware (Doorbell, Indoor Cam, etc.)

### Files Modified

| File | Lines Changed | Description |
|------|--------------|-------------|
| `api/client.py` | 273 → 292 (+19) | New `call_bidi_stream()` method using `grpc.aio.stream_stream` |
| `api/video.py` | 219 → 367 (+148) | `initiate_webrtc()`, `send_webrtc_candidate()`, `close_webrtc_call()` with v3 bidirectional stream proto imports |
| `camera.py` | 243 → 385 (+142) | `async_handle_async_webrtc_offer()`, `async_on_webrtc_candidate()`, `close_webrtc_session()`, `_read_webrtc_ice_candidates()`, `_webrtc_sessions` / `_webrtc_read_tasks` state |
| `tests/unit/test_camera.py` | 730 → 915 (+185) | 8 new WebRTC tests + `webrtc_models` / `homeassistant.components.camera.webrtc` stubs |

### Test Coverage (Phase 3 additions)

| Test | What It Verifies |
|------|-----------------|
| `test_async_handle_webrtc_offer_video_edge` | Full offer→answer flow for video edge device |
| `test_async_handle_webrtc_offer_non_video_edge_rejected` | Motion cams reject WebRTC with error |
| `test_async_handle_webrtc_offer_device_missing` | Missing device returns error |
| `test_async_handle_webrtc_offer_space_missing` | Missing space returns error |
| `test_async_handle_webrtc_offer_no_answer` | No Ajax answer returns error |
| `test_async_on_webrtc_candidate_forwards_to_ajax` | HA ICE candidate forwarded to Ajax stream |
| `test_async_on_webrtc_candidate_no_session` | Unknown session ignored silently |
| `test_close_webrtc_session_cleanup` | Session close cancels task and removes state |

### Notes

- The v3 `StreamWebrtcService/execute` endpoint is a **bidirectional** stream:
  client writes `StreamWebrtcRequest` messages and reads `StreamWebrtcResponse` messages.
- `Init` message carries `space_locator`, `video_edge_id`, `initial_streams`, and
  `allow_large_rtp_packets`. The response contains `ice_servers` and the actual
  `streams` that were accepted by the video edge.
- The `Stream` proto uses `channel_guid` as the source identifier and `ST_MAIN`
  (`StreamType = 1`) for the primary video stream. `FrameTypeId` filters include
  `FT_VIDEO` and `FT_AUDIO`.
- HA detects native WebRTC support automatically: `Camera._supports_native_async_webrtc`
  is True when `async_handle_async_webrtc_offer` is overridden. This causes
  `camera_capabilities.frontend_stream_types` to include `StreamType.WEB_RTC`.
- No go2rtc proxy is needed — HA's built-in WebRTC frontend handles the peer
  connection directly, and this integration only acts as a signaling bridge.
- The actual media stream (RTP video/audio) travels **directly** between the HA
  frontend and the Ajax camera via the WebRTC peer connection, not through the
  HA backend.

---

## 5. Phase 4 — Advanced Features (COMPLETE)

**Status:** 5.1 (Cloud Archive), 5.3 (ONVIF), 5.4 (Detection Zones), and 5.5 (Video Notifications) complete. 5.2 (Two-Way Audio) deferred.

### 5.1 Cloud Archive Playback (COMPLETE)

#### Implementation Summary

Two new methods on `VideoApi` query the Ajax cloud archive for video fragment metadata
and pre-signed MP4 download URLs. Archive helper methods on `AjaxCamera` delegate to
the video API, allowing users to programmatically fetch archive footage via service
calls or templates.

#### Cloud Archive API

| RPC Method | Type | Purpose |
|-----------|------|---------|
| `getVideoFragmentsInfo` | unary | Returns `{fragment_id, ts, duration}` for a time range |
| `streamVideoFragmentsData` | server-streaming | Returns pre-signed MP4 fragment URLs (with `enable_presigned_urls_for_fragment_data=true`) |

#### Changes

- **`api/video.py`:** New proto imports for `cloud_archive_endpoints_pb2_grpc`,
  `get_video_fragments_info_pb2`, `stream_video_fragments_data_pb2`.
- **`api/video.py`:** `get_video_fragments_info(video_edge_id, channel_guid, space_id, start_ts, end_ts)`
  — calls `getVideoFragmentsInfo` unary RPC, returns list of fragment metadata dicts.
- **`api/video.py`:** `get_video_fragment_urls(video_edge_id, channel_guid, space_id)`
  — opens `streamVideoFragmentsData` server stream, collects all `data_url` pre-signed
  MP4 URLs, returns list of strings.
- **`camera.py`:** `get_archive_fragments(start_ts, end_ts)` — delegates to
  `video_api.get_video_fragments_info`. Returns empty list for non-video-edge types.
- **`camera.py`:** `get_archive_fragment_urls()` — delegates to
  `video_api.get_video_fragment_urls`. Returns pre-signed MP4 URLs.
- **`camera.py`:** `_resolve_space()` — shared helper that resolves the Ajax Space
  for this camera's device.
- **Tests:** 4 new tests covering archive fragments and URL retrieval for both
  video-edge and non-video-edge device types.

#### Notes

- Pre-signed URLs are valid for a limited time (typically 1 hour). Callers should
  download the fragments promptly after retrieving the URLs.
- The `streamVideoFragmentsData` endpoint also supports `fragment_part_data` with
  `data_url_header` (Range header) for partial downloads — not yet exposed.
- Full HA Media Browser integration (timeline browsing, thumbnail extraction) is
  deferred to a future release.

### 5.2 Two-Way Audio (NOT STARTED)

- [ ] Implement audio streaming via `WebrtcService` audio channels
- [ ] Enable HA's microphone-to-camera audio pipeline
- [ ] Audio codec support (G.711, AAC, etc.)

### 5.3 ONVIF Direct Integration (COMPLETE)

#### Implementation Summary

The existing `get_onvif_and_rtsp_settings` endpoint already returns `onvif_http_port`
and `onvif_usernames`. Phase 5.3 caches these on the `AjaxCamera` entity and exposes
them via `extra_state_attributes` so users can configure external ONVIF tools
(Frigate, Blue Iris, ONVIF Device Manager).

#### Changes

- **`camera.py`:** `_onvif_port` / `_onvif_usernames` / `_onvif_settings_resolved`
  attributes, cached during `_resolve_video_edge_stream()`.
- **`camera.py`:** New `extra_state_attributes` property exposing `onvif_port` and
  `onvif_usernames`.
- **Tests:** 3 new tests for ONVIF caching and attribute exposure.

#### Notes

- ONVIF passwords are **not retrievable** via the API. Users must manually enter the
  password in their ONVIF tool. The camera's default ONVIF credentials are typically
  printed on a sticker on the device.
- PTZ control via ONVIF is not yet implemented — requires HA ONVIF integration or
  direct ONVIF protocol calls.

### 5.4 Detection Zone Configuration (DEFERRED)

Requires proto analysis of `set_video_notification_settings`, `get_video_notification_settings`,
and related endpoints. The protos exist but need careful cross-referencing with the
Ajax mobile app's configuration flow to understand which fields control line crossing,
motion zones, and object detection classes.

- [ ] Line crossing detection settings
- [ ] Motion detection zones
- [ ] Object detection (human/vehicle/pet)

**Available protos and compiled stubs in codebase:**
`get_video_notification_settings`, `set_video_notification_settings`,
`get_video_notification_alert_settings`, `set_video_notification_alert_settings`,
`set_video_edge_detectors_enabled_by_notification_types`,
`video_notification_settings` (common model with `VideoNotificationType` enum).

### 5.5 Video Notification Enhancements (COMPLETE)

#### Implementation Summary

The core infrastructure for parsing video events from FCM pushes was already in place
(`_extract_event_with_compiled_protos` walks `VideoEventQualifier`, `VIDEO_EVENT_TAG_MAP`
maps tags to HA event types). Phase 5.5 expands the event mappings and adds proper
`VideoNotificationSource` extraction for device info enrichment.

#### Changes

- **`const.py`:** Expanded `VIDEO_EVENT_TAG_MAP` with `human_detected`, `pet_detected`,
  `car_detected`, `tamper_opened`, `device_moved`, `device_hit` (6 new entries).
- **`const.py`:** Added `pet_detected` and `car_detected` to `TAG_PRIORITY` at tier 80
  (sensor activity).
- **`logbook.py`:** Added logbook descriptions for `human_detected`, `pet_detected`,
  `car_detected`.
- **`notification.py`:** New `_extract_video_source_info()` static method — scans raw
  push bytes for `VideoNotificationSource` and extracts `device_id`, `device_name`,
  `room_name`, `video_edge_type`.
- **`notification.py`:** `_parse_and_fire_event()` now calls both `_extract_source_info`
  (hub source) and `_extract_video_source_info` (video source); video source values
  win where both are present.
- **Tests:** 7 new tests for video event tag mappings and source extraction.

#### New Video Event Types

| Ajax Tag | HA Event Type | Logbook Description |
|----------|--------------|---------------------|
| `ring_button_pressed` | `doorbell_pressed` | Doorbell pressed |
| `motion_detected` | `motion` | Motion detected |
| `human_detected` | `human_detected` | Human detected |
| `pet_detected` | `pet_detected` | Pet detected |
| `car_detected` | `car_detected` | Vehicle detected |
| `tamper_opened` | `tamper` | Tamper |
| `device_moved` | `tamper` | Tamper |
| `device_hit` | `tamper` | Tamper |

---

## 6. Known Limitations & Open Questions

### 6.1 Current Limitations

| Limitation | Severity | Mitigation |
|-----------|----------|------------|
| **VideoEdge RTSP URL is heuristic** — `rtsp://{device_id}:{port}/stream` is constructed from device ID, not an actual hostname/IP. The device ID is likely NOT a valid hostname. | **High** | Need to determine the actual hostname/IP of the VideoEdge NVR/hub. The `device_id` may map to an internal Ajax identifier, not a network address. |
| **No preview images yet** — `channel_preview.image_url` is not consumed. Camera entity shows blank image until a photo is captured (PhOD models) or indefinitely (non-PhOD models). | **High** | **Resolved in Phase 2** — preview images refresh every 120s via `VideoEdgeService/streamUpdates`. |
| **No WebRTC streaming** — Ajax's native protocol is not yet implemented. Legacy RTSP fallback only covers hub-connected cameras. | **Medium** | **Resolved in Phase 3** — native WebRTC signaling via HA's `async_handle_async_webrtc_offer` using v3 `StreamWebrtcService/execute`. |
| **`video_edge_*` hub_id is self-referential** — The `DevicesApi._parse_video_edge_channel()` sets `hub_id = profile.id` because VideoEdge devices don't have a parent hub. This means `_resolve_hub_camera_stream()` won't match for video edge devices (correctly — they use `_resolve_video_edge_stream()` instead). But `_resolve_video_edge_stream()` uses the device's own ID to look up a space, which requires iterating spaces. | **Low** | This is handled correctly in the current code, but worth noting for future refactors. |
| **No stream lifecycle management** — Once `stream_source` returns a URL, HA's Stream component opens a persistent ffmpeg process. If the Ajax session expires, the stream may fail silently. | **Medium** | Consider adding session refresh hooks or re-querying `stream_source` on stream failure. |
| **No ONVIF credential exposure** — `get_onvif_and_rtsp_settings` returns ONVIF usernames but not passwords. Direct ONVIF streaming requires the password. | **Medium** | **Partially resolved in Phase 4** — usernames and port exposed via `extra_state_attributes`. Passwords remain irretrievable; users must enter them in their ONVIF tool (default password is usually on a device sticker). |

### 6.2 Open Questions

1. **What is the correct RTSP URL format for VideoEdge devices?**
   - Current heuristic: `rtsp://{device_id}:{rtsp_port}/stream`
   - Actual format may be `rtsp://{NVR_IP}:{rtsp_port}/{channel_path}` or
     `rtsp://{login}:{password}@{NVR_IP}:{rtsp_port}/...`
   - Need to confirm with Ajax or by inspecting the official app's network traffic

2. **Is the `SurveillanceCamerasService/getStreamSettings` endpoint still active**
   on current firmware? It's a v2 legacy endpoint.

3. **Can we get the NVR/hub IP address from the gRPC API?** The `VideoEdgeBase`
   and `HubNetworkState` protos may contain IP information we need.

4. **Does Ajax allow direct LAN RTSP access** from third-party clients, or is all
   video traffic routed through the cloud?

5. **What is the WebRTC TURN/STUN infrastructure?** URLs, authentication, fallback
   behavior when P2P is unavailable.

---

## 7. Required External Information

To proceed with Phases 2-4, the following information is needed from **Ajax Systems**
(the user is a Pre-Sales Manager with access to internal resources):

### Critical (blocks further development)

| # | Information Needed | Phase |
|---|-------------------|-------|
| 1 | Internal VideoEdge API documentation (endpoint reference, auth flow) | 2, 3 |
| 2 | Correct RTSP URL format for VideoEdge devices | 1 (refinement), 2 |
| 3 | WebRTC ICE server configuration (STUN/TURN URLs, credentials) | 3 |
| 4 | `StreamVideoPlayerService.execute` response specification (what does the stream contain?) | 2 |
| 5 | Whether direct LAN RTSP access is supported for VideoEdge devices | 1 (refinement) |

### High Priority

| # | Information Needed | Phase |
|---|-------------------|-------|
| 6 | Per-device video capabilities matrix (which support RTSP, WebRTC, dual-stream, audio) | 2, 3 |
| 7 | Minimum firmware versions for video features | 1 (validation) |
| 8 | Video authentication model (does gRPC session token suffice for video streams?) | 2, 3 |
| 9 | WebRTC implementation guide / SDP constraints | 3 |
| 10 | `SurveillanceCameraStreamSettings` deprecation status | 1 (validation) |

### Medium Priority

| # | Information Needed | Phase |
|---|-------------------|-------|
| 11 | `channel_preview.image_url` format, refresh rate, auth | 2 |
| 12 | Cloud archive pre-signed URL availability and retention | 4 |
| 13 | ONVIF credential retrieval via API | 4 |
| 14 | Hub hardware requirements (is NVR required for video?) | 1 (docs) |
| 15 | Test/sandbox environment for development | All |

---

## 8. File Change Log

### Files Modified (Phase 1)

| File | Lines Changed | Description |
|------|--------------|-------------|
| `api/video.py` | **NEW** 152 lines | VideoApi class with 3 gRPC methods |
| `camera.py` | 133 → 214 (+81) | Expanded device types, stream_source, motion_detection, supported_features |
| `coordinator.py` | 924 → 930 (+6) | VideoApi import, init, property |
| `api/__init__.py` | 34 → 38 (+4) | VideoApi export |
| `tests/unit/test_camera.py` | 332 → 492 (+160) | 15 new tests |

### Files Modified (Phase 2)

| File | Lines Changed | Description |
|------|--------------|-------------|
| `api/video.py` | 152 → 204 (+52) | `get_channel_preview_urls()` — calls `VideoEdgeService/streamUpdates`, returns `{channel_id: image_url}` |
| `coordinator.py` | 930 → 995 (+65) | `video_preview_urls` dict, `_maybe_refresh_preview_urls()` with 120s interval |
| `camera.py` | 214 → 240 (+26) | Preview URL fallback in `async_camera_image()`, `_download_preview()`, `_is_valid_preview_url()` |
| `tests/unit/test_camera.py` | 526 → 695 (+169) | 9 new tests for preview image flow |

### Files Modified (Phase 3)

| File | Lines Changed | Description |
|------|--------------|-------------|
| `api/client.py` | 273 → 292 (+19) | New `call_bidi_stream()` — opens `grpc.aio.stream_stream` for manual write/read |
| `api/video.py` | 204 → 367 (+163) | `initiate_webrtc()`, `send_webrtc_candidate()`, `close_webrtc_call()` using v3 `StreamWebrtcService/execute` |
| `camera.py` | 240 → 385 (+145) | `async_handle_async_webrtc_offer()`, `async_on_webrtc_candidate()`, `close_webrtc_session()`, `_read_webrtc_ice_candidates()` |
| `tests/unit/test_camera.py` | 695 → 915 (+220) | 8 new WebRTC tests + `webrtc_models` and `camera.webrtc` stubs |

### Files Modified (Phase 4)

| File | Lines Changed | Description |
|------|--------------|-------------|
| `const.py` | 456 → 467 (+11) | Expanded `VIDEO_EVENT_TAG_MAP` (+5 entries), added `TAG_PRIORITY` for new types |
| `notification.py` | 943 → 1013 (+70) | `_extract_video_source_info()` for `VideoNotificationSource`, wired into `_parse_and_fire_event` |
| `logbook.py` | 37 → 40 (+3) | Logbook descriptions for `human_detected`, `pet_detected`, `car_detected` |
| `camera.py` | 386 → 403 (+17) | ONVIF settings cache + `extra_state_attributes` property |
| `tests/unit/test_notification.py` | 1798 → 1930 (+132) | 7 new tests for video event mappings and source extraction |
| `tests/unit/test_camera.py` | 915 → 1028 (+113) | 3 new ONVIF tests + 4 new cloud archive tests |
| `api/video.py` | 367 → 468 (+101) | `get_video_fragments_info()` + `get_video_fragment_urls()` using CloudArchiveService |
| `camera.py` | 403 → 455 (+52) | `get_archive_fragments()`, `get_archive_fragment_urls()`, `_resolve_space()` |

### Files NOT Modified (Phase 1)

These files were analyzed but not changed:
- `const.py` — no new constants needed yet
- `api/models.py` — `Device` model unchanged; video info resolved at entity level
- `api/devices.py` — already parses `video_edge_channel` correctly
- `api/client.py` — no changes needed
- `api/media.py` — no changes needed
- `notification.py` — no changes needed
- `binary_sensor.py` — video edge devices already get motion/tamper binary sensors
- `button.py` — photo capture button unchanged

### Proto Analysis Reference

The following proto files were analyzed during Phase 1 investigation and are available
for future phases:

| Proto Source | Purpose |
|-------------|---------|
| `v3/.../get_video_edge_onvif_and_rtsp_settings/` | ONVIF/RTSP port config (used in Phase 1) |
| `systems/.../surveillance_cameras_endpoints.proto` | Legacy hub camera stream settings (used in Phase 1) |
| `v3/.../stream_video_player/` | Video player channel listing (used in Phase 1) |
| `v3/.../get_video_stream_settings/` | Codec/quality config (Phase 3) |
| `v3/.../set_video_stream_settings/` | Codec/quality config (Phase 3) |
| `systems/.../webrtc_endpoints.proto` | WebRTC signaling (Phase 3) |
| `systems/.../videoedge/` (30+ files) | Full VideoEdge management (Phase 3-4) |
| `systems/.../cloud_archive_mvp/` | Cloud archive playback (Phase 4) |
| `v3/.../video/videoedge/` (26 files) | Common video models |

---

## 9. Test Status

| Metric | Before Phase 1 | After Phase 1 | After Phase 2 | After Phase 3 | After Phase 4 |
|--------|---------------|---------------|---------------|---------------|---------------|
| Total unit tests | 1384 | 1399 | 1408 | 1416 | 1429 |
| Camera tests | 25 | 40 | 49 | 57 | 60 |
| Notification tests | — | — | — | — | 24 (7 new video) |
| Test pass rate | 100% | 100% | 100% | 100% | 100% |
| Coverage | 87.4% | 87.4% | 87.4% | 87.4% | 87.4% |
| Lint (ruff) | Clean | Clean | Clean | Clean | Clean |
| Typecheck (mypy) | 6 pre-existing errors | 6 pre-existing errors | 6 pre-existing errors | 6 pre-existing errors | 6 pre-existing errors |
| Format (ruff format) | Compliant | Compliant | Compliant | Compliant | Compliant |

### Running Tests

```bash
# Install dependencies
python3 -m venv .venv
.venv/bin/pip install homeassistant pytest pytest-asyncio pytest-cov numpy
.venv/bin/pip install grpcio protobuf firebase-messaging pycryptodome aiohttp

# Run tests
PYTHONPATH=$(pwd) .venv/bin/python -m pytest tests/unit/ -v

# Run camera tests only
PYTHONPATH=$(pwd) .venv/bin/python -m pytest tests/unit/test_camera.py -v

# Lint
.venv/bin/ruff check custom_components/aegis_ajax/

# Typecheck (expects 6 pre-existing errors unrelated to video)
.venv/bin/mypy custom_components/aegis_ajax/ --ignore-missing-imports --exclude 'proto/'
```
