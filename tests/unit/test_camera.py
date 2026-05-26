"""Tests for camera entities."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _stub_camera_module() -> None:
    """Stub out homeassistant.components.camera to avoid numpy dependency."""
    camera_mod = ModuleType("homeassistant.components.camera")

    class CameraEntityFeature:
        STREAM = 1

    class Camera:
        """Minimal Camera stub."""

        EntityFeature = CameraEntityFeature

        def __init__(self) -> None:
            pass

    camera_mod.Camera = Camera  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.camera"] = camera_mod

    webrtc_mod = ModuleType("homeassistant.components.camera.webrtc")

    @dataclass(frozen=True)
    class WebRTCAnswer:
        answer: str

    @dataclass(frozen=True)
    class WebRTCCandidate:
        candidate: object

    @dataclass(frozen=True)
    class WebRTCError:
        code: str
        message: str

    @dataclass(frozen=True)
    class WebRTCSession:
        session_id: str

    webrtc_mod.WebRTCAnswer = WebRTCAnswer  # type: ignore[attr-defined]
    webrtc_mod.WebRTCCandidate = WebRTCCandidate  # type: ignore[attr-defined]
    webrtc_mod.WebRTCError = WebRTCError  # type: ignore[attr-defined]
    webrtc_mod.WebRTCSession = WebRTCSession  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.camera.webrtc"] = webrtc_mod

    # Stub webrtc_models so lazy imports inside camera.py succeed
    webrtc_models_mod = ModuleType("webrtc_models")

    @dataclass(frozen=True)
    class RTCIceCandidateInit:
        candidate: str
        sdp_mid: str | None = None
        sdp_m_line_index: int | None = None

        def to_dict(self) -> dict[str, Any]:
            return {
                "candidate": self.candidate,
                "sdpMid": self.sdp_mid,
                "sdpMLineIndex": self.sdp_m_line_index,
            }

    webrtc_models_mod.RTCIceCandidateInit = RTCIceCandidateInit  # type: ignore[attr-defined]
    webrtc_models_mod.RTCConfiguration = object  # type: ignore[attr-defined]
    webrtc_models_mod.RTCIceServer = object  # type: ignore[attr-defined]
    webrtc_models_mod.RTCIceCandidate = RTCIceCandidateInit  # type: ignore[attr-defined]
    sys.modules["webrtc_models"] = webrtc_models_mod


_stub_camera_module()

from custom_components.aegis_ajax.camera import (  # noqa: E402
    CAMERA_DEVICE_TYPES,
    PHOD_DEVICE_TYPES,
    AjaxCamera,
)


class TestCameraDeviceTypes:
    def test_motion_cam_phod_is_camera(self) -> None:
        assert "motion_cam_phod" in CAMERA_DEVICE_TYPES

    def test_motion_cam_is_camera(self) -> None:
        assert "motion_cam" in CAMERA_DEVICE_TYPES

    def test_motion_cam_outdoor_is_camera(self) -> None:
        assert "motion_cam_outdoor" in CAMERA_DEVICE_TYPES

    def test_motion_cam_fibra_is_camera(self) -> None:
        assert "motion_cam_fibra" in CAMERA_DEVICE_TYPES

    def test_video_edge_doorbell_is_camera(self) -> None:
        assert "video_edge_doorbell" in CAMERA_DEVICE_TYPES

    def test_video_edge_turret_is_camera(self) -> None:
        assert "video_edge_turret" in CAMERA_DEVICE_TYPES

    def test_video_edge_bullet_is_camera(self) -> None:
        assert "video_edge_bullet" in CAMERA_DEVICE_TYPES

    def test_video_edge_minidome_is_camera(self) -> None:
        assert "video_edge_minidome" in CAMERA_DEVICE_TYPES

    def test_video_edge_indoor_is_camera(self) -> None:
        assert "video_edge_indoor" in CAMERA_DEVICE_TYPES


class TestPhodDeviceTypes:
    def test_motion_cam_phod_is_phod(self) -> None:
        assert "motion_cam_phod" in PHOD_DEVICE_TYPES

    def test_motion_cam_outdoor_phod_is_phod(self) -> None:
        assert "motion_cam_outdoor_phod" in PHOD_DEVICE_TYPES

    def test_motion_cam_fibra_base_is_phod(self) -> None:
        assert "motion_cam_fibra_base" in PHOD_DEVICE_TYPES

    def test_regular_motion_cam_is_not_phod(self) -> None:
        assert "motion_cam" not in PHOD_DEVICE_TYPES

    def test_motion_cam_outdoor_is_not_phod(self) -> None:
        assert "motion_cam_outdoor" not in PHOD_DEVICE_TYPES

    def test_video_edge_not_phod(self) -> None:
        assert "video_edge_doorbell" not in PHOD_DEVICE_TYPES

    def test_phod_types_are_subset_of_camera_types(self) -> None:
        assert PHOD_DEVICE_TYPES.issubset(CAMERA_DEVICE_TYPES)


class TestAjaxCamera:
    def test_unique_id(self) -> None:
        coordinator = MagicMock()
        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam_phod"
        )
        assert cam.unique_id == "aegis_ajax_d1_camera"

    def test_has_camera_image_method(self) -> None:
        coordinator = MagicMock()
        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam_phod"
        )
        assert hasattr(cam, "async_camera_image")

    def test_name_is_none(self) -> None:
        """Camera is the primary entity and adopts device name."""
        coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.name = "Front Camera"
        coordinator.devices = {"d1": mock_device}
        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam"
        )
        assert cam._attr_name is None

    def test_device_info_with_device(self) -> None:
        coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.id = "d1"
        mock_device.name = "Front Camera"
        mock_device.device_type = "motion_cam"
        mock_device.hub_id = "h1"
        coordinator.devices = {"d1": mock_device}
        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam"
        )
        assert cam._attr_device_info is not None
        assert ("aegis_ajax", "d1") in cam._attr_device_info["identifiers"]

    def test_device_info_without_device(self) -> None:
        coordinator = MagicMock()
        coordinator.devices = {}
        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam"
        )
        assert not hasattr(cam, "_attr_device_info") or cam._attr_device_info is None

    def test_available_when_device_online(self) -> None:
        coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.is_online = True
        coordinator.devices = {"d1": mock_device}
        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam"
        )
        assert cam.available is True

    def test_unavailable_when_device_missing(self) -> None:
        coordinator = MagicMock()
        coordinator.devices = {}
        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam"
        )
        assert cam.available is False

    def test_motion_cam_has_motion_detection_disabled(self) -> None:
        coordinator = MagicMock()
        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam"
        )
        assert cam.motion_detection_enabled is False

    def test_video_edge_has_motion_detection_enabled(self) -> None:
        coordinator = MagicMock()
        cam = AjaxCamera(
            coordinator=coordinator,
            device_id="v1",
            hub_id="v1",
            device_type="video_edge_doorbell",
        )
        assert cam.motion_detection_enabled is True

    def test_supported_features_includes_stream(self) -> None:
        coordinator = MagicMock()
        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam_phod"
        )
        from homeassistant.components.camera import Camera

        assert cam.supported_features == Camera.EntityFeature.STREAM

    @pytest.mark.asyncio
    async def test_async_camera_image_downloads_from_cached_url(self) -> None:
        """When button stored a URL, camera downloads and returns the image."""
        coordinator = MagicMock()
        coordinator.last_photo_urls = {
            "d1": "https://hubs-uploaded-resources.s3.amazonaws.com/photo.jpg"
        }

        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam_phod"
        )

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.read = AsyncMock(return_value=b"fake_image_data")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        with patch(
            "custom_components.aegis_ajax.camera.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await cam.async_camera_image()

        assert result == b"fake_image_data"
        assert "d1" not in coordinator.last_photo_urls

    @pytest.mark.asyncio
    async def test_async_camera_image_uses_cached_url_from_button(self) -> None:
        """When button already retrieved a URL, camera uses it directly."""
        coordinator = MagicMock()
        coordinator.last_photo_urls = {
            "d1": "https://hubs-uploaded-resources.s3.amazonaws.com/photo.jpg"
        }

        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam_phod"
        )

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.read = AsyncMock(return_value=b"cached_url_data")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        with patch(
            "custom_components.aegis_ajax.camera.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await cam.async_camera_image()

        assert result == b"cached_url_data"
        # URL should be consumed (popped)
        assert "d1" not in coordinator.last_photo_urls

    @pytest.mark.asyncio
    async def test_async_camera_image_returns_none_when_capture_fails(self) -> None:
        """When capture_photo returns None, no URL wait happens and cached image returned."""
        coordinator = MagicMock()
        coordinator.last_photo_urls = {}
        coordinator.devices_api.capture_photo = AsyncMock(return_value=None)
        mock_listener = MagicMock()
        mock_listener.wait_for_notification_id = AsyncMock(return_value=None)
        coordinator.notification_listener = mock_listener

        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam_phod"
        )
        cam._last_image = None

        result = await cam.async_camera_image()
        assert result is None
        mock_listener.wait_for_notification_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_async_camera_image_returns_cached_when_no_url(self) -> None:
        """When both notification_id and push URL fail, cached image is returned."""
        coordinator = MagicMock()
        coordinator.last_photo_urls = {}
        coordinator.devices_api.capture_photo = AsyncMock(return_value="d1")
        mock_listener = MagicMock()
        mock_listener.wait_for_notification_id = AsyncMock(return_value=None)
        mock_listener.wait_for_photo_url = AsyncMock(return_value=None)
        coordinator.notification_listener = mock_listener

        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam_phod"
        )
        cam._last_image = b"old_image"

        result = await cam.async_camera_image()
        assert result == b"old_image"

    @pytest.mark.asyncio
    async def test_async_camera_image_media_stream_no_url(self) -> None:
        """When notification_id arrives but media stream returns no URL."""
        coordinator = MagicMock()
        coordinator.last_photo_urls = {}
        coordinator.devices_api.capture_photo = AsyncMock(return_value="d1")
        mock_listener = MagicMock()
        mock_listener.wait_for_notification_id = AsyncMock(return_value="NOTIF456")
        coordinator.notification_listener = mock_listener
        coordinator.media_api.get_photo_url = AsyncMock(return_value=None)

        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam_phod"
        )
        cam._last_image = b"old_image"

        result = await cam.async_camera_image()
        assert result == b"old_image"

    @pytest.mark.asyncio
    async def test_async_camera_image_handles_http_error(self) -> None:
        coordinator = MagicMock()
        coordinator.last_photo_urls = {}
        coordinator.devices_api.capture_photo = AsyncMock(return_value="d1")
        mock_listener = MagicMock()
        mock_listener.wait_for_notification_id = AsyncMock(return_value="NOTIF789")
        coordinator.notification_listener = mock_listener
        coordinator.media_api.get_photo_url = AsyncMock(
            return_value="https://app.prod.ajax.systems/photo.jpg"
        )

        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam_phod"
        )
        cam._last_image = b"old_image"

        mock_resp = AsyncMock()
        mock_resp.status = 404
        mock_resp.read = AsyncMock(return_value=b"not found")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        with patch(
            "custom_components.aegis_ajax.camera.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await cam.async_camera_image()

        # Returns old cached image since 404 didn't update it
        assert result == b"old_image"

    @pytest.mark.asyncio
    async def test_async_camera_image_handles_download_exception(self) -> None:
        coordinator = MagicMock()
        coordinator.last_photo_urls = {}
        coordinator.devices_api.capture_photo = AsyncMock(return_value="d1")
        mock_listener = MagicMock()
        mock_listener.wait_for_notification_id = AsyncMock(return_value="NOTIF_EXC")
        coordinator.notification_listener = mock_listener
        coordinator.media_api.get_photo_url = AsyncMock(
            return_value="https://app.prod.ajax.systems/photo.jpg"
        )

        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam_phod"
        )
        cam._last_image = b"cached"

        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=Exception("network error"))

        with patch(
            "custom_components.aegis_ajax.camera.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await cam.async_camera_image()

        # Should return cached image on exception
        assert result == b"cached"

    @pytest.mark.asyncio
    async def test_async_camera_image_no_notification_listener(self) -> None:
        """When notification_listener is None, capture returns but no URL wait."""
        coordinator = MagicMock()
        coordinator.last_photo_urls = {}
        coordinator.devices_api.capture_photo = AsyncMock(return_value="d1")
        coordinator.notification_listener = None

        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam_phod"
        )
        cam._last_image = b"cached"

        result = await cam.async_camera_image()
        assert result == b"cached"

    @pytest.mark.asyncio
    async def test_stream_source_hub_camera_rtsp(self) -> None:
        coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.id = "d1"
        mock_device.hub_id = "h1"
        mock_device.is_online = True
        coordinator.devices = {"d1": mock_device}

        mock_space = MagicMock()
        mock_space.id = "s1"
        mock_space.hub_id = "h1"
        coordinator.spaces = {"s1": mock_space}

        coordinator.video_api.get_surveillance_camera_stream_url = AsyncMock(
            return_value="rtsp://192.168.1.100:554/stream"
        )

        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam"
        )

        result = await cam.stream_source()
        assert result == "rtsp://192.168.1.100:554/stream"
        coordinator.video_api.get_surveillance_camera_stream_url.assert_called_once_with(
            hub_hex_id="h1", camera_hex_id="d1"
        )

    @pytest.mark.asyncio
    async def test_stream_source_hub_camera_no_url(self) -> None:
        coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.id = "d1"
        mock_device.hub_id = "h1"
        coordinator.devices = {"d1": mock_device}

        mock_space = MagicMock()
        mock_space.id = "s1"
        mock_space.hub_id = "h1"
        coordinator.spaces = {"s1": mock_space}

        coordinator.video_api.get_surveillance_camera_stream_url = AsyncMock(return_value=None)

        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam"
        )

        result = await cam.stream_source()
        assert result is None

    @pytest.mark.asyncio
    async def test_stream_source_video_edge_rtsp(self) -> None:
        coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.id = "ve1"
        mock_device.hub_id = "ve1"
        coordinator.devices = {"ve1": mock_device}

        mock_space = MagicMock()
        mock_space.id = "s1"
        mock_space.hub_id = "ve1"
        coordinator.spaces = {"s1": mock_space}

        coordinator.video_api.get_onvif_and_rtsp_settings = AsyncMock(
            return_value=(None, 554, None)
        )

        cam = AjaxCamera(
            coordinator=coordinator,
            device_id="ve1",
            hub_id="ve1",
            device_type="video_edge_doorbell",
        )

        result = await cam.stream_source()
        assert result == "rtsp://ve1:554/stream"

    @pytest.mark.asyncio
    async def test_stream_source_video_edge_no_rtsp_port(self) -> None:
        coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.id = "ve1"
        mock_device.hub_id = "ve1"
        coordinator.devices = {"ve1": mock_device}

        mock_space = MagicMock()
        mock_space.id = "s1"
        mock_space.hub_id = "ve1"
        coordinator.spaces = {"s1": mock_space}

        coordinator.video_api.get_onvif_and_rtsp_settings = AsyncMock(
            return_value=(None, None, None)
        )

        cam = AjaxCamera(
            coordinator=coordinator,
            device_id="ve1",
            hub_id="ve1",
            device_type="video_edge_doorbell",
        )

        result = await cam.stream_source()
        assert result is None

    @pytest.mark.asyncio
    async def test_stream_source_device_missing(self) -> None:
        coordinator = MagicMock()
        coordinator.devices = {}
        coordinator.spaces = {}

        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam"
        )

        result = await cam.stream_source()
        assert result is None

    @pytest.mark.asyncio
    async def test_stream_source_cached(self) -> None:
        coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.id = "d1"
        mock_device.hub_id = "h1"
        coordinator.devices = {"d1": mock_device}

        mock_space = MagicMock()
        mock_space.id = "s1"
        mock_space.hub_id = "h1"
        coordinator.spaces = {"s1": mock_space}

        coordinator.video_api.get_surveillance_camera_stream_url = AsyncMock(
            return_value="rtsp://cached"
        )

        cam = AjaxCamera(
            coordinator=coordinator, device_id="d1", hub_id="h1", device_type="motion_cam"
        )

        first = await cam.stream_source()
        assert first == "rtsp://cached"
        assert coordinator.video_api.get_surveillance_camera_stream_url.call_count == 1

        second = await cam.stream_source()
        assert second == "rtsp://cached"
        assert coordinator.video_api.get_surveillance_camera_stream_url.call_count == 1

    @pytest.mark.asyncio
    async def test_async_camera_image_uses_preview_url_fallback(self) -> None:
        coordinator = MagicMock()
        coordinator.last_photo_urls = {}
        coordinator.video_preview_urls = {"ve1": "https://preview.ajax.systems/snapshot.jpg"}

        cam = AjaxCamera(
            coordinator=coordinator,
            device_id="ve1",
            hub_id="ve1",
            device_type="video_edge_doorbell",
        )

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.read = AsyncMock(return_value=b"preview_image_data")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        with patch(
            "custom_components.aegis_ajax.camera.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await cam.async_camera_image()

        assert result == b"preview_image_data"

    @pytest.mark.asyncio
    async def test_async_camera_image_preview_skip_on_bad_url(self) -> None:
        coordinator = MagicMock()
        coordinator.last_photo_urls = {}
        coordinator.video_preview_urls = {"ve1": "ftp://invalid/url"}

        cam = AjaxCamera(
            coordinator=coordinator,
            device_id="ve1",
            hub_id="ve1",
            device_type="video_edge_doorbell",
        )
        cam._last_image = b"cached_fallback"

        result = await cam.async_camera_image()
        assert result == b"cached_fallback"

    @pytest.mark.asyncio
    async def test_async_camera_image_preview_handles_download_error(self) -> None:
        coordinator = MagicMock()
        coordinator.last_photo_urls = {}
        coordinator.video_preview_urls = {"ve1": "https://preview.ajax.systems/fail.jpg"}

        cam = AjaxCamera(
            coordinator=coordinator,
            device_id="ve1",
            hub_id="ve1",
            device_type="video_edge_doorbell",
        )
        cam._last_image = b"cached"

        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=Exception("timeout"))

        with patch(
            "custom_components.aegis_ajax.camera.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await cam.async_camera_image()

        assert result == b"cached"

    @pytest.mark.asyncio
    async def test_async_camera_image_preview_overrides_last_image(self) -> None:
        coordinator = MagicMock()
        coordinator.last_photo_urls = {}
        coordinator.video_preview_urls = {"ve1": "https://preview.ajax.systems/live.jpg"}

        cam = AjaxCamera(
            coordinator=coordinator,
            device_id="ve1",
            hub_id="ve1",
            device_type="video_edge_doorbell",
        )
        cam._last_image = b"old_preview"

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.read = AsyncMock(return_value=b"fresh_preview")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        with patch(
            "custom_components.aegis_ajax.camera.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await cam.async_camera_image()

        assert result == b"fresh_preview"
        assert cam._last_image == b"fresh_preview"

    @pytest.mark.asyncio
    async def test_async_camera_image_photo_takes_priority_over_preview(self) -> None:
        coordinator = MagicMock()
        coordinator.last_photo_urls = {"d1": "https://hubs-uploaded-resources.s3/photo.jpg"}
        coordinator.video_preview_urls = {"d1": "https://preview.ajax.systems/preview.jpg"}

        cam = AjaxCamera(
            coordinator=coordinator,
            device_id="d1",
            hub_id="h1",
            device_type="motion_cam_phod",
        )

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.read = AsyncMock(return_value=b"photo_data")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        with patch(
            "custom_components.aegis_ajax.camera.async_get_clientsession",
            return_value=mock_session,
        ):
            result = await cam.async_camera_image()

        assert result == b"photo_data"
        assert "d1" not in coordinator.last_photo_urls

    def test_is_valid_preview_url_accepts_https(self) -> None:
        from custom_components.aegis_ajax.camera import AjaxCamera

        assert AjaxCamera._is_valid_preview_url("https://preview.ajax.systems/img.jpg") is True

    def test_is_valid_preview_url_accepts_http(self) -> None:
        from custom_components.aegis_ajax.camera import AjaxCamera

        assert AjaxCamera._is_valid_preview_url("http://192.168.1.1/snapshot.jpg") is True

    def test_is_valid_preview_url_rejects_ftp(self) -> None:
        from custom_components.aegis_ajax.camera import AjaxCamera

        assert AjaxCamera._is_valid_preview_url("ftp://files/file.jpg") is False

    def test_is_valid_preview_url_rejects_empty(self) -> None:
        from custom_components.aegis_ajax.camera import AjaxCamera

        assert AjaxCamera._is_valid_preview_url("not_a_url") is False

    @pytest.mark.asyncio
    async def test_async_handle_webrtc_offer_video_edge(self) -> None:
        """WebRTC offer/answer flow for a video edge device."""
        coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.id = "ve1"
        mock_device.hub_id = "ve1"
        mock_device.is_online = True
        coordinator.devices = {"ve1": mock_device}

        mock_space = MagicMock()
        mock_space.id = "s1"
        mock_space.hub_id = "ve1"
        coordinator.spaces = {"s1": mock_space}

        mock_call = AsyncMock()
        coordinator.video_api.initiate_webrtc = AsyncMock(
            return_value=("ajax_session_123", "v=0\r\nanswer_sdp", mock_call)
        )
        coordinator.video_api.close_webrtc_call = AsyncMock()

        cam = AjaxCamera(
            coordinator=coordinator,
            device_id="ve1",
            hub_id="ve1",
            device_type="video_edge_doorbell",
        )

        messages: list[Any] = []

        def send_message(msg: Any) -> None:  # noqa: ANN401
            messages.append(msg)

        await cam.async_handle_async_webrtc_offer("v=0\r\noffer_sdp", "ha_session_1", send_message)

        # Should have sent exactly one WebRTCAnswer
        assert len(messages) == 1
        assert messages[0].answer == "v=0\r\nanswer_sdp"
        assert "ha_session_1" in cam._webrtc_sessions
        coordinator.video_api.initiate_webrtc.assert_called_once_with(
            space_id="s1",
            video_edge_id="ve1",
            channel_id="ve1",
            offer_sdp="v=0\r\noffer_sdp",
        )

        # Cleanup
        await cam.close_webrtc_session("ha_session_1")
        assert "ha_session_1" not in cam._webrtc_sessions

    @pytest.mark.asyncio
    async def test_async_handle_webrtc_offer_non_video_edge_rejected(self) -> None:
        """Motion cam devices should reject WebRTC offers."""
        coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.id = "d1"
        mock_device.hub_id = "h1"
        coordinator.devices = {"d1": mock_device}

        mock_space = MagicMock()
        mock_space.id = "s1"
        mock_space.hub_id = "h1"
        coordinator.spaces = {"s1": mock_space}

        cam = AjaxCamera(
            coordinator=coordinator,
            device_id="d1",
            hub_id="h1",
            device_type="motion_cam",
        )

        messages: list[Any] = []

        def send_message(msg: Any) -> None:  # noqa: ANN401
            messages.append(msg)

        await cam.async_handle_async_webrtc_offer("offer", "ha_session_2", send_message)

        assert len(messages) == 1
        assert messages[0].code == "webrtc_offer_failed"

    @pytest.mark.asyncio
    async def test_async_handle_webrtc_offer_device_missing(self) -> None:
        """Camera should error when device is missing during WebRTC."""
        coordinator = MagicMock()
        coordinator.devices = {}
        cam = AjaxCamera(
            coordinator=coordinator,
            device_id="ve1",
            hub_id="ve1",
            device_type="video_edge_doorbell",
        )

        messages: list[Any] = []

        def send_message(msg: Any) -> None:  # noqa: ANN401
            messages.append(msg)

        await cam.async_handle_async_webrtc_offer("offer", "ha_session_3", send_message)

        assert len(messages) == 1
        assert messages[0].code == "webrtc_offer_failed"

    @pytest.mark.asyncio
    async def test_async_handle_webrtc_offer_space_missing(self) -> None:
        """Camera should error when space is missing during WebRTC."""
        coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.id = "ve1"
        mock_device.hub_id = "ve1"
        coordinator.devices = {"ve1": mock_device}
        coordinator.spaces = {}

        cam = AjaxCamera(
            coordinator=coordinator,
            device_id="ve1",
            hub_id="ve1",
            device_type="video_edge_doorbell",
        )

        messages: list[Any] = []

        def send_message(msg: Any) -> None:  # noqa: ANN401
            messages.append(msg)

        await cam.async_handle_async_webrtc_offer("offer", "ha_session_4", send_message)

        assert len(messages) == 1
        assert messages[0].code == "webrtc_offer_failed"

    @pytest.mark.asyncio
    async def test_async_handle_webrtc_offer_no_answer(self) -> None:
        """Camera should error when Ajax returns no answer."""
        coordinator = MagicMock()
        mock_device = MagicMock()
        mock_device.id = "ve1"
        mock_device.hub_id = "ve1"
        coordinator.devices = {"ve1": mock_device}

        mock_space = MagicMock()
        mock_space.id = "s1"
        mock_space.hub_id = "ve1"
        coordinator.spaces = {"s1": mock_space}

        coordinator.video_api.initiate_webrtc = AsyncMock(return_value=(None, None, None))

        cam = AjaxCamera(
            coordinator=coordinator,
            device_id="ve1",
            hub_id="ve1",
            device_type="video_edge_doorbell",
        )

        messages: list[Any] = []

        def send_message(msg: Any) -> None:  # noqa: ANN401
            messages.append(msg)

        await cam.async_handle_async_webrtc_offer("offer", "ha_session_5", send_message)

        assert len(messages) == 1
        assert messages[0].code == "webrtc_offer_failed"

    @pytest.mark.asyncio
    async def test_async_on_webrtc_candidate_forwards_to_ajax(self) -> None:
        """ICE candidate from HA should be forwarded to Ajax stream."""
        coordinator = MagicMock()
        coordinator.video_api.send_webrtc_candidate = AsyncMock()

        cam = AjaxCamera(
            coordinator=coordinator,
            device_id="ve1",
            hub_id="ve1",
            device_type="video_edge_doorbell",
        )

        mock_call = AsyncMock()
        cam._webrtc_sessions["ha_session_6"] = {
            "call": mock_call,
            "webrtc_session_id": "ajax_456",
        }

        candidate = MagicMock()
        candidate.to_dict.return_value = {
            "candidate": "candidate:1234",
            "sdpMid": "0",
            "sdpMLineIndex": 0,
        }

        await cam.async_on_webrtc_candidate("ha_session_6", candidate)

        coordinator.video_api.send_webrtc_candidate.assert_called_once()
        args = coordinator.video_api.send_webrtc_candidate.call_args
        assert args[0][0] is mock_call

    @pytest.mark.asyncio
    async def test_async_on_webrtc_candidate_no_session(self) -> None:
        """ICE candidate for unknown session should be ignored."""
        coordinator = MagicMock()
        coordinator.video_api.send_webrtc_candidate = AsyncMock()

        cam = AjaxCamera(
            coordinator=coordinator,
            device_id="ve1",
            hub_id="ve1",
            device_type="video_edge_doorbell",
        )

        candidate = MagicMock()
        await cam.async_on_webrtc_candidate("unknown_session", candidate)
        coordinator.video_api.send_webrtc_candidate.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_webrtc_session_cleanup(self) -> None:
        """Closing a session should cancel reader and remove state."""
        coordinator = MagicMock()
        coordinator.video_api.close_webrtc_call = AsyncMock()

        cam = AjaxCamera(
            coordinator=coordinator,
            device_id="ve1",
            hub_id="ve1",
            device_type="video_edge_doorbell",
        )

        mock_call = AsyncMock()
        cam._webrtc_sessions["ha_session_7"] = {
            "call": mock_call,
            "webrtc_session_id": "ajax_789",
        }
        # Add a done task to avoid actually running a coroutine
        done_task = MagicMock()
        done_task.done.return_value = True
        cam._webrtc_read_tasks["ha_session_7"] = done_task  # type: ignore[assignment]

        await cam.close_webrtc_session("ha_session_7")

        assert "ha_session_7" not in cam._webrtc_sessions
        assert "ha_session_7" not in cam._webrtc_read_tasks
