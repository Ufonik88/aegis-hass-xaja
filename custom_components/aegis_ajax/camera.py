"""Camera entities for Ajax Security (photos and video streams)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

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

    @property
    def supported_features(self) -> int:
        return Camera.EntityFeature.STREAM
