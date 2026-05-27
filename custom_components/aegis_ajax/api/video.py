"""Video API: retrieve stream URLs and settings for Ajax cameras."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from custom_components.aegis_ajax.api.client import AjaxGrpcClient

_LOGGER = logging.getLogger(__name__)

# Proto imports are placed after standard-library imports because the
# _proto_path module (imported by api/__init__.py) must run first.
# isort: off
from systems.ajax.api.mobile.v2.common.space import (  # noqa: E402
    space_locator_pb2,
)
from systems.ajax.api.mobile.v2.video.videoedge import (  # noqa: E402
    stream_updates_request_pb2,
)
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
from v3.mobilegwsvc.service.stream_webrtc import (  # noqa: E402
    request_pb2 as webrtc_req,
    response_pb2 as webrtc_resp,
)
from systems.ajax.api.mobile.v2.common.video.webrtc import (  # noqa: E402
    ice_candidate_pb2,
    session_description_pb2,
    stream_pb2,
)
from systems.ajax.api.mobile.v2.common.video import (  # noqa: E402
    types_pb2,
)
from systems.ajax.api.mobile.v2.video.cloud_archive_mvp import (  # noqa: E402
    cloud_archive_endpoints_pb2_grpc,
    get_video_fragments_info_pb2,
    stream_video_fragments_data_pb2,
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

    async def get_channel_preview_urls(self, space_id: str) -> dict[str, str]:
        """Retrieve preview snapshot URLs for all video edge channels in a space.

        Opens a short-lived stream to VideoEdgeService/streamUpdates to capture
        the InitialState snapshot, then closes the stream. Returns a dict
        mapping device_id → image_url.
        """
        try:
            locator = space_locator_pb2.SpaceLocator(space_id=space_id)
            request = stream_updates_request_pb2.StreamVideoEdgeUpdatesRequest(
                space_locator=locator,
            )
            stream = await self._client.call_server_stream(
                "/systems.ajax.api.mobile.v2.video.videoedge.VideoEdgeService/streamUpdates",
                request,
                stream_updates_request_pb2.StreamVideoEdgeUpdatesResponse,
                timeout=15,
            )

            results: dict[str, str] = {}
            async for raw_response in stream:
                if not raw_response.HasField("success"):
                    break

                success = raw_response.success
                if success.HasField("initial_state"):
                    for ve in success.initial_state.video_edges:
                        for ch in ve.channels:
                            if ch.HasField("channel_preview") and ch.channel_preview.image_url:
                                channel_id = ch.guid
                                results[channel_id] = str(ch.channel_preview.image_url)
                break

            _LOGGER.debug(
                "Retrieved %d channel preview URLs for space %s",
                len(results),
                space_id,
            )
            return results

        except Exception:
            _LOGGER.debug(
                "Error getting channel preview URLs for space %s",
                space_id,
                exc_info=True,
            )
            return {}

    async def initiate_webrtc(
        self,
        space_id: str,
        video_edge_id: str,
        channel_id: str,
        offer_sdp: str,
    ) -> tuple[str | None, str | None, Any]:
        """Initiate a WebRTC session and exchange offer/answer.

        Opens a bidirectional stream to ``StreamWebrtcService/execute``,
        sends an ``Init`` followed by an ``Offer``, and captures the
        ``Init`` and ``Answer`` responses from Ajax.

        Returns:
            A 3-tuple of ``(webrtc_session_id, answer_sdp, call_object)``.
            ``call_object`` is the active ``grpc.aio.StreamStreamCall``;
            the caller must keep it alive while the session is active and
            forward ICE candidates via :meth:`send_webrtc_candidate`.
        """
        try:
            locator = space_locator_pb2.SpaceLocator(space_id=space_id)

            stream_msg = stream_pb2.Stream(
                channel_guid=channel_id,
                type=types_pb2.ST_MAIN,
                filter=[
                    types_pb2.FrameTypeId(frame_type=types_pb2.FT_VIDEO),
                    types_pb2.FrameTypeId(frame_type=types_pb2.FT_AUDIO),
                ],
                live=stream_pb2.Stream.Live(),
            )

            init_request = webrtc_req.StreamWebrtcRequest(
                init=webrtc_req.StreamWebrtcRequest.Init(
                    space_locator=locator,
                    video_edge_id=video_edge_id,
                    initial_streams=[stream_msg],
                    allow_large_rtp_packets=True,
                ),
            )

            call = await self._client.call_bidi_stream(
                "/systems.ajax.api.ecosystem.v3.mobilegwsvc.service.stream_webrtc.StreamWebrtcService/execute",
                webrtc_resp.StreamWebrtcResponse,
                timeout=30,
            )

            await call.write(init_request)

            # Read Init response (session_id, ice_servers, streams)
            raw_init = await call.read()
            if raw_init is None or not raw_init.HasField("success"):
                _LOGGER.debug("WebRTC init failed: no success response")
                await call.cancel()
                return None, None, None

            init_success = raw_init.success
            if not init_success.HasField("init"):
                _LOGGER.debug("WebRTC init failed: missing init field")
                await call.cancel()
                return None, None, None

            webrtc_session_id = init_success.init.streams[0].id if init_success.init.streams else ""
            _LOGGER.debug(
                "WebRTC init success: session_id=%s, ice_servers=%d",
                webrtc_session_id,
                len(init_success.init.ice_servers),
            )

            # Send HA's offer
            offer_request = webrtc_req.StreamWebrtcRequest(
                offer=webrtc_req.StreamWebrtcRequest.Offer(
                    session_description=session_description_pb2.SessionDescription(
                        type="offer",
                        sdp=offer_sdp,
                    ),
                ),
            )
            await call.write(offer_request)

            # Read Answer response
            raw_answer = await call.read()
            if raw_answer is None or not raw_answer.HasField("success"):
                _LOGGER.debug("WebRTC answer failed: no success response")
                await call.cancel()
                return None, None, None

            answer_success = raw_answer.success
            if not answer_success.HasField("answer"):
                _LOGGER.debug("WebRTC answer failed: missing answer field")
                await call.cancel()
                return None, None, None

            answer_sdp = answer_success.answer.session_description.sdp
            _LOGGER.debug(
                "WebRTC answer received for session %s",
                webrtc_session_id,
            )
            return webrtc_session_id, answer_sdp, call

        except Exception:
            _LOGGER.debug(
                "Error initiating WebRTC for video_edge %s channel %s",
                video_edge_id,
                channel_id,
                exc_info=True,
            )
            return None, None, None

    @staticmethod
    async def send_webrtc_candidate(
        call: Any,  # noqa: ANN401
        candidate: dict[str, Any],
    ) -> None:
        """Forward an ICE candidate to the Ajax WebRTC stream.

        ``candidate`` is a dict with keys ``sdp_mid``, ``sdp_mline_index``,
        and ``candidate`` (the full ICE candidate string).
        """
        try:
            if call is None or getattr(call, "done", lambda: True)():
                return
            ice = ice_candidate_pb2.IceCandidate(
                sdp_mid=candidate.get("sdp_mid", candidate.get("sdpMid", "")),
                sdp_mline_index=candidate.get(
                    "sdp_mline_index", candidate.get("sdpMLineIndex", 0)
                ),
                sdp=candidate.get("candidate", ""),
            )
            request = webrtc_req.StreamWebrtcRequest(
                new_ice_candidate=webrtc_req.StreamWebrtcRequest.NewIceCandidate(
                    candidate=ice,
                ),
            )
            await call.write(request)
        except Exception:
            _LOGGER.debug("Error sending WebRTC ICE candidate", exc_info=True)

    @staticmethod
    async def close_webrtc_call(call: Any) -> None:  # noqa: ANN401
        """Gracefully close a WebRTC bidirectional stream."""
        try:
            if call is not None:
                await call.cancel()
        except Exception:
            _LOGGER.debug("Error closing WebRTC call", exc_info=True)

    async def get_video_fragments_info(
        self,
        video_edge_id: str,
        channel_guid: str,
        space_id: str,
        start_ts_seconds: int = 0,
        end_ts_seconds: int = 0,
        stream_type: int = 1,  # types_pb2.ST_MAIN
    ) -> list[dict[str, int]]:
        """Query cloud archive for video fragment metadata within a time range.

        Returns a list of dicts with keys ``fragment_id``, ``ts`` (epoch seconds),
        and ``duration`` (milliseconds). An empty list means no fragments are
        available for the requested time range.
        """
        try:
            channel = self._client._get_channel()
            call_md = self._client._session.get_call_metadata()
            stub = cloud_archive_endpoints_pb2_grpc.CloudArchiveServiceStub(channel)

            request = get_video_fragments_info_pb2.CloudArchiveGetVideoFragmentsInfoRequest(
                video_edge_guid=video_edge_id,
                channel_guid=channel_guid,
                stream_type=stream_type,
                space_id=space_id,
            )

            from google.protobuf.timestamp_pb2 import Timestamp  # noqa: PLC0415

            if start_ts_seconds > 0:
                start_ts = Timestamp()
                start_ts.FromSeconds(start_ts_seconds)
                request.ts_range.min_value.CopyFrom(start_ts)
            if end_ts_seconds > 0:
                end_ts = Timestamp()
                end_ts.FromSeconds(end_ts_seconds)
                request.ts_range.max_value.CopyFrom(end_ts)

            response = await stub.getVideoFragmentsInfo(
                request, metadata=call_md, timeout=10
            )

            results: list[dict[str, int]] = []
            for frag in response.fragments:
                results.append({
                    "fragment_id": frag.fragment_id,
                    "ts": frag.ts,
                    "duration": frag.duration,
                })
            return results

        except Exception:
            _LOGGER.debug(
                "Error getting video fragments info for video_edge %s channel %s",
                video_edge_id,
                channel_guid,
                exc_info=True,
            )
            return []

    async def get_video_fragment_urls(
        self,
        video_edge_id: str,
        channel_guid: str,
        space_id: str,
        stream_type: int = 1,  # types_pb2.ST_MAIN
        timeout: float | None = 30,
    ) -> list[str]:
        """Retrieve pre-signed MP4 download URLs for cloud archive fragments.

        Opens a server-streaming RPC to ``streamVideoFragmentsData`` with
        ``enable_presigned_urls_for_fragment_data=true``. Collects every
        ``data_url`` from the ``fragment_data`` responses and returns them
        as a list of HTTPS URLs. Each URL points to a downloadable MP4
        fragment.

        Callers should close the stream promptly once they have the URLs
        they need — the server continues streaming until the client
        disconnects.
        """
        try:
            request = stream_video_fragments_data_pb2.CloudArchiveStreamVideoFragmentsDataRequest(
                video_edge_guid=video_edge_id,
                channel_guid=channel_guid,
                stream_type=stream_type,
                space_id=space_id,
                enable_presigned_urls_for_fragment_data=True,
            )
            stream = await self._client.call_server_stream(
                "/systems.ajax.api.mobile.v2.video.cloud_archive_mvp.CloudArchiveService/streamVideoFragmentsData",
                request,
                stream_video_fragments_data_pb2.CloudArchiveStreamVideoFragmentsDataResponse,
                timeout=timeout,
            )

            urls: list[str] = []
            async for raw_response in stream:
                which = raw_response.WhichOneof("response_union")
                if which == "session_id":
                    continue
                if which == "fragment_data":
                    fd = raw_response.fragment_data
                    if fd.HasField("error") and fd.error.code != 0:
                        continue
                    if fd.data_url:
                        urls.append(fd.data_url)
                # fragment_part_data is for Range: header partial downloads;
                # we only collect the full-fragment data_url for now.

            _LOGGER.debug(
                "Retrieved %d cloud archive fragment URLs for video_edge %s",
                len(urls),
                video_edge_id,
            )
            return urls

        except Exception:
            _LOGGER.debug(
                "Error retrieving cloud archive fragment URLs for video_edge %s",
                video_edge_id,
                exc_info=True,
            )
            return []
