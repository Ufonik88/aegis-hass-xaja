# MASTER TODO — Video Functionality for Aegis for Ajax

> **Last Updated:** 2026-05-26
> **Status:** Phase 1 Complete / Phase 2 Pending

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
3. [Phase 2 — Snapshot/Preview Images (PLANNED)](#3-phase-2--snapshotpreview-images-planned)
4. [Phase 3 — WebRTC Live Streaming (PLANNED)](#4-phase-3--webrtc-live-streaming-planned)
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

## 3. Phase 2 — Snapshot/Preview Images (PLANNED)

**Not started. Dependencies: real-device testing of Phase 1.**

### Goal
Display preview/snapshot images for video edge devices inside the HA camera entity
(when a live stream is not active), using `Channel.channel_preview.image_url` from
the Ajax video edge channel proto.

### Tasks

- [ ] **3.1** Call `StreamVideoPlayerService` at coordinator startup to populate a
  `video_preview_urls: dict[str, str]` dict on the coordinator (keyed by device_id)
- [ ] **3.2** Override `async_camera_image()` in `AjaxCamera` to check
  `coordinator.video_preview_urls` as a fallback before `_get_last_image()`
- [ ] **3.3** Add periodic refresh of preview URLs (e.g. every 30 seconds)
- [ ] **3.4** Add URL validation for preview images (reuse `_is_valid_photo_url` or
  extend to handle video edge image domains)
- [ ] **3.5** Write unit tests for preview image retrieval and caching
- [ ] **3.6** Test with real hardware (Doorbell, Indoor Cam, etc.)

### Files to Modify
- `api/video.py` — add `get_channel_preview_url()` method
- `camera.py` — modify `async_camera_image()` for preview fallback
- `coordinator.py` — add `video_preview_urls` dict and refresh logic
- `tests/unit/test_camera.py` — add preview tests

---

## 4. Phase 3 — WebRTC Live Streaming (PLANNED)

**Not started. Dependencies: Ajax WebRTC API documentation.**

### Goal
Implement live video streaming via Ajax's native WebRTC protocol. This is how the
official Ajax mobile app streams video from all modern camera types (VideoEdge, Doorbell,
etc.).

### Key Protos to Implement

| Service | Method | Type |
|---------|--------|------|
| `WebrtcService` | `initiate` | unary_stream — returns ICE servers, SDP offers |
| `WebrtcService` | `askStreams` | unary_unary — query available streams |
| `WebrtcService` | `sendAnswer` | unary_unary — WebRTC signaling |
| `WebrtcService` | `sendOffer` | unary_unary — WebRTC signaling |
| `WebrtcService` | `suggestNewIceCandidate` | unary_unary — ICE candidate exchange |

### Architectural Challenge
HA does not have native WebRTC camera support in the core `Camera` entity. The typical
approach is to use a third-party integration like **go2rtc** or **WebRTC Camera** that
handles the WebRTC client side. Options:

1. **Option A:** Implement WebRTC signaling in this integration and expose via a custom
   frontend card
2. **Option B:** Proxy through go2rtc — this integration fetches the WebRTC offer from
   Ajax, go2rtc consumes it, HA's Stream component gets HLS from go2rtc
3. **Option C:** Stream video frames via gRPC `StreamVideoPlayerService.execute` and
   expose as MJPEG

**Recommendation:** Option B (go2rtc proxy) — lowest integration complexity.

### Tasks (high-level, to be refined)

- [ ] **4.1** Implement `WebrtcService.initiate` call in `VideoApi`
- [ ] **4.2** Handle ICE server configuration (STUN/TURN URLs from Ajax)
- [ ] **4.3** Implement SDP offer/answer exchange
- [ ] **4.4** Integrate with go2rtc or similar WebRTC-to-HLS bridge
- [ ] **4.5** Expose stream URL from go2rtc as `stream_source` on `AjaxCamera`
- [ ] **4.6** Support dual-stream (main/sub) selection
- [ ] **4.7** Write integration tests
- [ ] **4.8** Test with real hardware

### Files to Modify/Create
- `api/video.py` — add WebRTC methods
- `camera.py` — WebRTC stream source override
- `coordinator.py` — go2rtc lifecycle management

---

## 5. Phase 4 — Advanced Features (PLANNED)

**Not started. Dependencies: Phase 2 + Phase 3 completion.**

### 5.1 Cloud Archive Playback

- [ ] Call `CloudArchiveService.streamVideoFragmentsData` for pre-signed MP4 URLs
- [ ] Expose archive timeline in HA Media Browser
- [ ] Handle fragment part download with Range headers

### 5.2 Two-Way Audio

- [ ] Implement audio streaming via `WebrtcService` audio channels
- [ ] Enable HA's microphone-to-camera audio pipeline
- [ ] Audio codec support (G.711, AAC, etc.)

### 5.3 ONVIF Direct Integration

- [ ] Use `get_onvif_and_rtsp_settings` to retrieve ONVIF credentials
- [ ] Construct ONVIF URLs for direct camera access
- [ ] PTZ control via ONVIF (if supported by camera)

### 5.4 Detection Zone Configuration

- [ ] Line crossing detection settings
- [ ] Motion detection zones
- [ ] Object detection (human/vehicle/pet)

### 5.5 Video Notification Enhancements

- [ ] Parse `video_notification` protos from FCM pushes
- [ ] Surface video-specific events (motion, ring, human detected)
- [ ] Drive HA automations from video events

---

## 6. Known Limitations & Open Questions

### 6.1 Current Limitations

| Limitation | Severity | Mitigation |
|-----------|----------|------------|
| **VideoEdge RTSP URL is heuristic** — `rtsp://{device_id}:{port}/stream` is constructed from device ID, not an actual hostname/IP. The device ID is likely NOT a valid hostname. | **High** | Need to determine the actual hostname/IP of the VideoEdge NVR/hub. The `device_id` may map to an internal Ajax identifier, not a network address. |
| **No preview images yet** — `channel_preview.image_url` is not consumed. Camera entity shows blank image until a photo is captured (PhOD models) or indefinitely (non-PhOD models). | **High** | Phase 2 will address this. |
| **No WebRTC streaming** — Ajax's native protocol is not yet implemented. Legacy RTSP fallback only covers hub-connected cameras. | **Medium** | Phase 3 will address this. |
| **`video_edge_*` hub_id is self-referential** — The `DevicesApi._parse_video_edge_channel()` sets `hub_id = profile.id` because VideoEdge devices don't have a parent hub. This means `_resolve_hub_camera_stream()` won't match for video edge devices (correctly — they use `_resolve_video_edge_stream()` instead). But `_resolve_video_edge_stream()` uses the device's own ID to look up a space, which requires iterating spaces. | **Low** | This is handled correctly in the current code, but worth noting for future refactors. |
| **No stream lifecycle management** — Once `stream_source` returns a URL, HA's Stream component opens a persistent ffmpeg process. If the Ajax session expires, the stream may fail silently. | **Medium** | Consider adding session refresh hooks or re-querying `stream_source` on stream failure. |
| **No ONVIF credential exposure** — `get_onvif_and_rtsp_settings` returns ONVIF usernames but not passwords. Direct ONVIF streaming requires the password. | **Medium** | Passwords may be retrievable via a separate endpoint, or users may need to enter them in the integration config flow. |

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

| Metric | Before Phase 1 | After Phase 1 |
|--------|---------------|---------------|
| Total unit tests | 1384 | 1399 |
| Camera tests | 25 | 40 |
| Test pass rate | 100% | 100% |
| Coverage | 87.4% | 87.4% (unchanged — new code not integration-tested) |
| Lint (ruff) | Clean | Clean |
| Typecheck (mypy) | 6 pre-existing errors | 6 pre-existing errors (no new errors) |
| Format (ruff format) | Compliant | Compliant |

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
