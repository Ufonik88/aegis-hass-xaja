"""Video API: retrieve stream URLs and settings for Ajax cameras."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from custom_components.aegis_ajax.api.client import AjaxGrpcClient

_LOGGER = logging.getLogger(__name__)

# Proto imports are placed after standard-library imports because the
# _proto_path module (imported by api/__init__.py) must run first.
# isort: off
from systems.ajax.mobile.v2.service.hub.company.media import (  # noqa: E402
    get_stream_settings_pb2,
    surveillance_cameras_endpoints_pb2_grpc,
)
from v3.mobilegwsvc.service.get_video_edge_onvif_and_rtsp_settings import (  # noqa: E402
    endpoint_pb2_grpc as onvif_rtsp_grpc,
    request_pb2 as onvif_rtsp_req,
)
from v3.mobilegwsvc.service.stream_video_player import (  # noqa: E402
    request_pb2 as player_req,
    response_pb2 as player_resp,
)
# isort: on


class VideoApi:
    def __init__(self, client: AjaxGrpcClient) -> None:
        self._client = client

    async def get_surveillance_camera_stream_url(
        self, hub_hex_id: str, camera_hex_id: str
    ) -> str | None:
        try:
            channel = self._client._get_channel()
            metadata = self._client._session.get_call_metadata()
            stub = surveillance_cameras_endpoints_pb2_grpc.SurveillanceCamerasServiceStub(channel)

            request = get_stream_settings_pb2.GetStreamSettingsRequest(
                hub_hex_id=hub_hex_id,
                camera_hex_id=camera_hex_id,
            )

            response = await stub.getStreamSettings(request, metadata=metadata, timeout=10)

            if response.HasField("success"):
                settings = response.success.stream_settings
                if (
                    settings.service_type == 1
                    and settings.HasField("stream_data_url")
                    and settings.stream_data_url
                ):
                    return str(settings.stream_data_url)
        except Exception:
            _LOGGER.debug(
                "Error fetching stream settings for camera %s on hub %s",
                camera_hex_id,
                hub_hex_id,
                exc_info=True,
            )
        return None

    async def get_onvif_and_rtsp_settings(
        self, space_id: str, video_edge_id: str
    ) -> tuple[int | None, int | None, list[str] | None]:
        try:
            channel = self._client._get_channel()
            metadata = self._client._session.get_call_metadata()
            stub = onvif_rtsp_grpc.GetVideoEdgeOnvifAndRtspSettingsServiceStub(channel)

            request = onvif_rtsp_req.GetVideoEdgeOnvifAndRtspSettingsRequest(
                space_id=space_id,
                video_edge_id=video_edge_id,
            )

            response = await stub.execute(request, metadata=metadata, timeout=10)

            if response.HasField("success"):
                onvif_port = None
                rtsp_port = None
                usernames = None

                if response.success.HasField("onvif_settings"):
                    onvif = response.success.onvif_settings
                    onvif_port = onvif.http_port if onvif.http_port else None
                    if onvif.users:
                        usernames = [u.name for u in onvif.users]

                if response.success.HasField("rtsp_settings"):
                    rtsp = response.success.rtsp_settings
                    rtsp_port = rtsp.http_port if rtsp.http_port else None

                return onvif_port, rtsp_port, usernames
        except Exception:
            _LOGGER.debug(
                "Error fetching ONVIF/RTSP settings for video_edge %s",
                video_edge_id,
                exc_info=True,
            )
        return None, None, None

    async def get_video_player_channels(self, space_id: str) -> list[dict[str, str | None]]:
        try:
            request = player_req.StreamVideoPlayerRequest(space_id=space_id)
            stream = await self._client.call_server_stream(
                "/systems.ajax.api.ecosystem.v3.mobilegwsvc.service.stream_video_player.StreamVideoPlayerService/execute",
                request,
                player_resp.StreamVideoPlayerResponse,
                timeout=15,
            )

            results: list[dict[str, str | None]] = []
            async for raw_response in stream:
                if not raw_response.HasField("success"):
                    continue

                success = raw_response.success
                if success.HasField("initial_state"):
                    for ve in success.initial_state.video_edges:
                        video_edge_id = ve.id
                        for ch in ve.channels:
                            results.append(
                                {
                                    "video_edge_id": video_edge_id,
                                    "channel_id": ch.id,
                                }
                            )

                if success.HasField("updates"):
                    for ve in success.updates.video_edges:
                        video_edge_id = ve.id
                        for ch in ve.channels:
                            results.append(
                                {
                                    "video_edge_id": video_edge_id,
                                    "channel_id": ch.id,
                                }
                            )

            return results

        except Exception:
            _LOGGER.debug(
                "Error streaming video player state for space %s",
                space_id,
                exc_info=True,
            )
            return []
