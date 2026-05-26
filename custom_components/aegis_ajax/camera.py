"""Camera entities for Ajax Security (photos and video streams)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.camera import Camera
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.aegis_ajax.coordinator import AjaxCobrandedCoordinator
from custom_components.aegis_ajax.entity import build_device_info

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from custom_components.aegis_ajax.api.models import Device

_LOGGER = logging.getLogger(__name__)

CAMERA_DEVICE_TYPES = {
    "motion_cam",
    "motion_cam_outdoor",
    "motion_cam_fibra",
    "motion_cam_phod",
    "motion_cam_outdoor_phod",
    "motion_cam_fibra_base",
    "video_edge_doorbell",
    "video_edge_turret",
    "video_edge_bullet",
    "video_edge_minidome",
    "video_edge_indoor",
    "video_edge_unknown",
}

PHOD_DEVICE_TYPES = {"motion_cam_phod", "motion_cam_outdoor_phod", "motion_cam_fibra_base"}

_VIDEO_EDGE_TYPES = {
    "video_edge_doorbell",
    "video_edge_turret",
    "video_edge_bullet",
    "video_edge_minidome",
    "video_edge_indoor",
    "video_edge_unknown",
}

_MOTION_CAM_TYPES = {
    "motion_cam",
    "motion_cam_outdoor",
    "motion_cam_fibra",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AjaxCobrandedCoordinator = entry.runtime_data
    entities = [
        AjaxCamera(
            coordinator=coordinator,
            device_id=device_id,
            hub_id=device.hub_id,
            device_type=device.device_type,
        )
        for device_id, device in coordinator.devices.items()
        if device.device_type in CAMERA_DEVICE_TYPES
    ]
    async_add_entities(entities)


class AjaxCamera(CoordinatorEntity[AjaxCobrandedCoordinator], Camera):
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        coordinator: AjaxCobrandedCoordinator,
        device_id: str,
        hub_id: str,
        device_type: str,
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._device_id = device_id
        self._hub_id = hub_id
        self._device_type = device_type
        self._attr_unique_id = f"aegis_ajax_{device_id}_camera"
        self._last_image_url: str | None = None
        self._last_image: bytes | None = None
        self._stream_url: str | None = None
        self._stream_url_resolved: bool = False
        self._webrtc_sessions: dict[str, Any] = {}
        self._webrtc_read_tasks: dict[str, asyncio.Task[None]] = {}
        device = coordinator.devices.get(device_id)
        if device:
            self._attr_device_info = build_device_info(device, coordinator.rooms)

    @property
    def _device(self) -> Device | None:
        return self.coordinator.devices.get(self._device_id)

    @property
    def available(self) -> bool:
        device = self._device
        return device is not None and device.is_online

    @property
    def motion_detection_enabled(self) -> bool:
        return self._device_type not in _MOTION_CAM_TYPES

    async def stream_source(self) -> str | None:
        if self._stream_url_resolved:
            return self._stream_url

        self._stream_url_resolved = True
        device = self._device
        if device is None:
            return None

        if self._device_type in _MOTION_CAM_TYPES:
            url = await self._resolve_hub_camera_stream(device)
            if url:
                self._stream_url = url
                return url

        if self._device_type in _VIDEO_EDGE_TYPES:
            url = await self._resolve_video_edge_stream(device)
            if url:
                self._stream_url = url
                return url

        return None

    async def _resolve_hub_camera_stream(self, device: Device) -> str | None:
        coord = self.coordinator
        space = next(
            (s for s in coord.spaces.values() if s.hub_id == device.hub_id),
            None,
        )
        if space is None:
            return None

        url = await coord.video_api.get_surveillance_camera_stream_url(
            hub_hex_id=device.hub_id,
            camera_hex_id=device.id,
        )
        return url

    async def _resolve_video_edge_stream(self, device: Device) -> str | None:
        coord = self.coordinator
        space = next(
            (s for s in coord.spaces.values() if s.hub_id == device.hub_id),
            None,
        )
        if space is None:
            return None

        _, rtsp_port, _ = await coord.video_api.get_onvif_and_rtsp_settings(
            space_id=space.id,
            video_edge_id=device.id,
        )

        if rtsp_port:
            return f"rtsp://{device.id}:{rtsp_port}/stream"
        return None

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,  # noqa: ARG002
    ) -> bytes | None:
        url = self.coordinator.last_photo_urls.pop(self._device_id, None)
        if url:
            return await self._download_image(url)
        preview_url = self.coordinator.video_preview_urls.get(self._device_id)
        if isinstance(preview_url, str) and preview_url:
            return await self._download_preview(preview_url)
        return await self._get_last_image()

    async def _get_last_image(self) -> bytes | None:
        if self._last_image is None:
            from custom_components.aegis_ajax.photo_storage import (  # noqa: PLC0415
                load_last_photo,
            )

            device = self.coordinator.devices.get(self._device_id)
            device_name = device.name if device else self._device_id
            self._last_image = await load_last_photo(self.hass, device_name)
        return self._last_image

    @staticmethod
    def _is_valid_photo_url(url: str) -> bool:
        from urllib.parse import urlparse  # noqa: PLC0415

        hostname = urlparse(url).hostname or ""
        return hostname.endswith(".ajax.systems") or "hubs-uploaded-resources" in hostname

    @staticmethod
    def _is_valid_preview_url(url: str) -> bool:
        from urllib.parse import urlparse  # noqa: PLC0415

        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.hostname)

    async def _download_image(self, url: str) -> bytes | None:
        import aiohttp  # noqa: PLC0415

        if not self._is_valid_photo_url(url):
            _LOGGER.warning("Rejected photo URL with unexpected domain: %s", url[:80])
            return self._last_image
        self._last_image_url = url
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    self._last_image = await resp.read()
        except Exception:
            _LOGGER.exception("Failed to download photo")
        return self._last_image

    async def _download_preview(self, url: str) -> bytes | None:
        import aiohttp  # noqa: PLC0415

        if not self._is_valid_preview_url(url):
            _LOGGER.debug("Rejected preview URL with unexpected domain: %s", url[:80])
            return self._last_image
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    self._last_image = await resp.read()
                    return self._last_image
        except Exception:
            _LOGGER.debug("Failed to download preview image from %s", url[:80])
        return self._last_image

    @property
    def supported_features(self) -> int:
        return Camera.EntityFeature.STREAM

    # ------------------------------------------------------------------
    # WebRTC live streaming (Phase 3)
    # ------------------------------------------------------------------

    async def async_handle_async_webrtc_offer(
        self, offer_sdp: str, session_id: str, send_message: Any  # noqa: ANN401
    ) -> None:
        """Handle a WebRTC offer from the Home Assistant frontend.

        Negotiates with Ajax's ``StreamWebrtcService/execute`` to obtain
        an answer SDP, then starts a background reader for ICE candidates.
        """
        from homeassistant.components.camera.webrtc import (  # noqa: PLC0415
            WebRTCAnswer,
            WebRTCError,
        )

        device = self._device
        if device is None:
            send_message(WebRTCError("webrtc_offer_failed", "Device unavailable"))
            return

        space = next(
            (s for s in self.coordinator.spaces.values() if s.hub_id == device.hub_id),
            None,
        )
        if space is None:
            send_message(WebRTCError("webrtc_offer_failed", "Space not found"))
            return

        if self._device_type not in _VIDEO_EDGE_TYPES:
            send_message(WebRTCError("webrtc_offer_failed", "Device does not support WebRTC"))
            return

        # Clean up any stale session for this HA session_id
        await self._close_webrtc_session(session_id)

        try:
            webrtc_session_id, answer_sdp, call = await self.coordinator.video_api.initiate_webrtc(
                space_id=space.id,
                video_edge_id=device.id,
                channel_id=device.id,
                offer_sdp=offer_sdp,
            )
        except Exception:
            _LOGGER.debug("WebRTC initiation failed", exc_info=True)
            send_message(WebRTCError("webrtc_offer_failed", "Failed to initiate WebRTC"))
            return

        if not webrtc_session_id or not answer_sdp or call is None:
            send_message(WebRTCError("webrtc_offer_failed", "No WebRTC answer received"))
            return

        self._webrtc_sessions[session_id] = {
            "call": call,
            "webrtc_session_id": webrtc_session_id,
        }

        # Send the answer back to HA
        send_message(WebRTCAnswer(answer=answer_sdp))

        # Start background reader for ICE candidates from Ajax
        task = asyncio.create_task(
            self._read_webrtc_ice_candidates(session_id, call, send_message)
        )
        self._webrtc_read_tasks[session_id] = task

    async def async_on_webrtc_candidate(
        self, session_id: str, candidate: Any  # noqa: ANN401
    ) -> None:
        """Forward an ICE candidate from the HA frontend to Ajax."""
        session = self._webrtc_sessions.get(session_id)
        if session is None:
            return
        call = session.get("call")
        if call is None:
            return

        candidate_dict = candidate.to_dict() if hasattr(candidate, "to_dict") else dict(candidate)
        await self.coordinator.video_api.send_webrtc_candidate(call, candidate_dict)

    async def _read_webrtc_ice_candidates(
        self,
        session_id: str,
        call: Any,  # noqa: ANN401
        send_message: Any,  # noqa: ANN401
    ) -> None:
        """Read ICE candidates from the Ajax stream and forward to HA."""
        from homeassistant.components.camera.webrtc import (  # noqa: PLC0415
            WebRTCCandidate,
        )
        from webrtc_models import RTCIceCandidateInit  # noqa: PLC0415

        try:
            while True:
                raw = await call.read()
                if raw is None:
                    break
                if not raw.HasField("success"):
                    continue
                success = raw.success
                if not success.HasField("new_ice_candidate"):
                    continue
                ice = success.new_ice_candidate.candidate
                if not ice.sdp:
                    continue
                candidate_init = RTCIceCandidateInit(
                    candidate=ice.sdp,
                    sdp_mid=ice.sdp_mid,
                    sdp_m_line_index=ice.sdp_mline_index,
                )
                send_message(WebRTCCandidate(candidate=candidate_init))
        except Exception:
            _LOGGER.debug(
                "WebRTC ICE candidate reader ended for session %s",
                session_id,
                exc_info=True,
            )
        finally:
            self._webrtc_sessions.pop(session_id, None)
            self._webrtc_read_tasks.pop(session_id, None)

    async def close_webrtc_session(self, session_id: str) -> None:
        """Close a WebRTC session (called by HA when the user stops viewing)."""
        await self._close_webrtc_session(session_id)

    async def _close_webrtc_session(self, session_id: str) -> None:
        """Internal cleanup for a WebRTC session."""
        task = self._webrtc_read_tasks.pop(session_id, None)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        session = self._webrtc_sessions.pop(session_id, None)
        if session is not None:
            call = session.get("call")
            if call is not None:
                await self.coordinator.video_api.close_webrtc_call(call)
